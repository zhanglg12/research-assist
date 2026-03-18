"""HTML digest generator for research-assist."""

import html


def _render_html_list(items: list[str], css_class: str) -> str:
    if not items:
        return ""
    rendered = "".join(f"<li>{html.escape(item)}</li>" for item in items)
    return f'<ul class="{css_class}">{rendered}</ul>'


def _truncate(text: str, limit: int) -> str:
    stripped = " ".join((text or "").split())
    if len(stripped) <= limit:
        return stripped
    return stripped[: max(0, limit - 1)].rstrip() + "..."


def _clamp_score(value: object) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = 0.0
    return max(0.0, min(1.0, score))


def _score_cell_style(value: object, kind: str) -> str:
    score = _clamp_score(value)
    intensity = 0.28 + score * 0.62
    shadow = 0.08 + score * 0.10
    if kind == "total":
        start = f"rgba(189, 106, 66, {0.18 + intensity * 0.42:.3f})"
        end = f"rgba(244, 221, 201, {0.70 + score * 0.18:.3f})"
        border = f"rgba(143, 75, 46, {0.18 + score * 0.36:.3f})"
        text = "#6b341f" if score >= 0.55 else "#71594a"
    elif kind == "map":
        start = f"rgba(184, 138, 56, {0.18 + intensity * 0.40:.3f})"
        end = f"rgba(244, 233, 197, {0.72 + score * 0.16:.3f})"
        border = f"rgba(148, 109, 33, {0.16 + score * 0.30:.3f})"
        text = "#6e4d12" if score >= 0.55 else "#74654f"
    else:
        start = f"rgba(105, 115, 88, {0.18 + intensity * 0.38:.3f})"
        end = f"rgba(225, 233, 215, {0.72 + score * 0.16:.3f})"
        border = f"rgba(86, 98, 69, {0.16 + score * 0.28:.3f})"
        text = "#41503a" if score >= 0.55 else "#666559"
    return (
        f"background: linear-gradient(180deg, {start}, {end});"
        f"border: 1px solid {border};"
        f"box-shadow: inset 0 1px 0 rgba(255,255,255,0.35), 0 10px 24px rgba(98, 69, 46, {shadow:.3f});"
        f"color: {text};"
    )


def _neighbor_display_items(neighbors: list[dict]) -> list[dict]:
    cleaned: list[dict] = []
    for neighbor in neighbors:
        if not isinstance(neighbor, dict):
            continue
        title = str(neighbor.get("title") or "").strip()
        if not title:
            continue
        cleaned.append(neighbor)
    if not cleaned:
        return []
    if len(cleaned) == 1:
        return cleaned[:1]
    first_title = str(cleaned[0].get("title") or "").strip()
    second_title = str(cleaned[1].get("title") or "").strip()
    if len(first_title) + len(second_title) <= 72:
        return cleaned[:2]
    return cleaned[:1]


def _render_neighbor_list(neighbors: list[dict]) -> str:
    display_neighbors = _neighbor_display_items(neighbors)
    if not display_neighbors:
        return ""
    items: list[str] = []
    for neighbor in display_neighbors:
        title = html.escape(str(neighbor.get("title") or "").strip())
        if not title:
            continue
        collection = html.escape(str(neighbor.get("collections") or "").strip())
        if collection:
            items.append(f"<li><strong>{title}</strong><span class=\"neighbor-meta\">{collection}</span></li>")
        else:
            items.append(f"<li><strong>{title}</strong></li>")
    if not items:
        return ""
    return f'<ul class="neighbor-list">{"".join(items)}</ul>'


def _render_neighbor_summary(summary: str) -> str:
    text = str(summary or "").strip()
    if not text:
        return ""
    return f'<p class="neighbor-summary">{html.escape(text)}</p>'


def _neighbor_candidates(scores: dict, review: dict) -> list[dict]:
    neighbors = scores.get("semantic_neighbors")
    if isinstance(neighbors, list) and neighbors:
        return neighbors

    top_title = str(scores.get("semantic_top_title") or "").strip()
    top_item_key = str(scores.get("semantic_top_item_key") or "").strip()
    if top_title:
        return [
            {
                "item_key": top_item_key or None,
                "title": top_title,
                "collections": None,
                "distance": scores.get("semantic_best_distance"),
            }
        ]

    zotero_comparison = review.get("zotero_comparison") if isinstance(review, dict) else None
    if isinstance(zotero_comparison, dict):
        related_items = zotero_comparison.get("related_items")
        if isinstance(related_items, list) and related_items:
            fallback_neighbors: list[dict] = []
            for item in related_items[:3]:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or "").strip()
                if not title:
                    continue
                relation = str(item.get("relation") or "").strip()
                fallback_neighbors.append(
                    {
                        "item_key": item.get("item_key"),
                        "title": title,
                        "collections": relation or None,
                        "distance": None,
                    }
                )
            if fallback_neighbors:
                return fallback_neighbors

    return []


def _neighbor_summary_text(scores: dict, review: dict) -> str:
    top_title = str(scores.get("semantic_top_title") or "").strip()
    if top_title:
        return f"Closest Zotero anchor: {top_title}"
    zotero_comparison = review.get("zotero_comparison") if isinstance(review, dict) else None
    if isinstance(zotero_comparison, dict):
        return str(zotero_comparison.get("summary") or "").strip()
    return ""


def _display_date(date_str: str) -> str:
    if len(date_str) >= 10 and date_str[4] == "-" and date_str[7] == "-":
        return f"{date_str[5:7]}/{date_str[8:10]}"
    return date_str


def _warm_page_css() -> str:
    return """
        :root {
            --bg: #f6ede1;
            --bg-deep: #ecdcc6;
            --paper: rgba(255, 250, 243, 0.9);
            --paper-strong: rgba(255, 248, 239, 0.96);
            --paper-muted: rgba(245, 233, 220, 0.82);
            --ink: #2f241d;
            --ink-soft: #5a4a3e;
            --muted: #8a7465;
            --line: rgba(122, 87, 61, 0.15);
            --accent: #bd6a42;
            --accent-deep: #8f4b2e;
            --accent-soft: rgba(189, 106, 66, 0.12);
            --olive: #697358;
            --olive-soft: rgba(105, 115, 88, 0.14);
            --gold: #b88a38;
            --shadow: 0 28px 70px rgba(98, 69, 46, 0.12);
            --shadow-soft: 0 16px 38px rgba(98, 69, 46, 0.08);
        }

        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: "Avenir Next", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
            background:
                radial-gradient(circle at 10% 8%, rgba(224, 175, 130, 0.42), transparent 26%),
                radial-gradient(circle at 84% 11%, rgba(207, 136, 93, 0.24), transparent 24%),
                radial-gradient(circle at 78% 72%, rgba(173, 149, 110, 0.14), transparent 28%),
                linear-gradient(180deg, #f8f1e7 0%, #f3e7d7 100%);
            color: var(--ink);
            line-height: 1.7;
            padding: 24px 16px 44px;
            min-height: 100vh;
        }

        body::before {
            content: "";
            position: fixed;
            inset: 0;
            pointer-events: none;
            background:
                repeating-linear-gradient(
                    0deg,
                    rgba(122, 93, 68, 0.025) 0,
                    rgba(122, 93, 68, 0.025) 1px,
                    transparent 1px,
                    transparent 8px
                );
            opacity: 0.45;
        }

        a {
            color: var(--accent-deep);
            text-decoration: none;
        }

        a:hover {
            color: var(--accent);
        }

        .page-shell {
            width: min(1320px, 100%);
            margin: 0 auto;
            position: relative;
            z-index: 1;
        }

        .hero {
            position: relative;
            overflow: hidden;
            padding: 32px;
            border: 1px solid rgba(151, 110, 81, 0.16);
            border-radius: 34px;
            background:
                linear-gradient(135deg, rgba(255, 249, 241, 0.97), rgba(245, 234, 220, 0.93)),
                radial-gradient(circle at top right, rgba(213, 149, 105, 0.18), transparent 30%);
            box-shadow: var(--shadow);
            margin-bottom: 20px;
        }

        .hero::after {
            content: "";
            position: absolute;
            right: -48px;
            top: -42px;
            width: 240px;
            height: 240px;
            border-radius: 50%;
            background: radial-gradient(circle, rgba(198, 132, 88, 0.2), transparent 68%);
            pointer-events: none;
        }

        .hero::before {
            content: "";
            position: absolute;
            inset: auto auto 12px -40px;
            width: 200px;
            height: 120px;
            border-radius: 999px;
            background: linear-gradient(90deg, rgba(184, 106, 69, 0.08), transparent);
            transform: rotate(-12deg);
            pointer-events: none;
        }

        .eyebrow {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            border-radius: 999px;
            padding: 7px 12px;
            background: rgba(184, 106, 69, 0.1);
            color: var(--accent-deep);
            font-size: 12px;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-bottom: 14px;
        }

        .hero h1 {
            font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif;
            font-size: clamp(38px, 6vw, 66px);
            line-height: 1.02;
            letter-spacing: -0.03em;
            max-width: 10ch;
            margin-bottom: 10px;
            font-weight: 600;
        }

        .hero-copy {
            max-width: 720px;
            color: var(--ink-soft);
            font-size: 17px;
            margin-bottom: 18px;
        }

        .hero-meta {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
        }

        .meta-pill {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 8px 12px;
            border-radius: 999px;
            background: rgba(255, 251, 246, 0.78);
            border: 1px solid rgba(151, 110, 81, 0.11);
            color: var(--ink-soft);
            font-size: 12px;
        }

        .overview-band {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 12px;
            margin-bottom: 18px;
        }

        .overview-card {
            border-radius: 18px;
            padding: 14px 16px;
            background: rgba(255, 249, 242, 0.82);
            border: 1px solid rgba(151, 110, 81, 0.12);
            box-shadow: var(--shadow-soft);
        }

        .overview-card.warm {
            background: linear-gradient(180deg, rgba(255, 245, 236, 0.95), rgba(244, 224, 208, 0.88));
        }

        .overview-card.olive {
            background: linear-gradient(180deg, rgba(247, 247, 240, 0.95), rgba(226, 231, 215, 0.9));
        }

        .overview-label {
            color: var(--muted);
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.09em;
            margin-bottom: 6px;
            font-weight: 700;
        }

        .overview-value {
            font-family: "Iowan Old Style", "Palatino Linotype", Georgia, serif;
            font-size: clamp(24px, 3vw, 34px);
            line-height: 1;
            margin-bottom: 4px;
        }

        .overview-copy {
            color: var(--ink-soft);
            font-size: 12px;
            line-height: 1.35;
        }

        .cards {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 18px;
        }

        .paper-card {
            position: relative;
            border-radius: 28px;
            padding: 22px;
            background:
                linear-gradient(180deg, rgba(255, 250, 243, 0.95), rgba(251, 244, 235, 0.93));
            border: 1px solid rgba(151, 110, 81, 0.14);
            box-shadow: 0 16px 40px rgba(102, 73, 50, 0.08);
            overflow: hidden;
            display: flex;
            flex-direction: column;
            min-height: 100%;
        }

        .paper-card::before {
            content: "";
            position: absolute;
            inset: 0;
            background: linear-gradient(135deg, rgba(255, 255, 255, 0.18), transparent 32%);
            pointer-events: none;
        }

        .paper-card.featured {
            grid-column: 1 / -1;
            padding: 26px;
            background:
                linear-gradient(135deg, rgba(255, 249, 241, 0.98), rgba(246, 234, 218, 0.94)),
                radial-gradient(circle at top right, rgba(188, 106, 67, 0.12), transparent 28%);
            box-shadow: 0 22px 52px rgba(98, 69, 46, 0.11);
        }

        .paper-card-shell {
            position: relative;
            z-index: 1;
            display: flex;
            flex-direction: column;
            gap: 0;
            flex: 1;
        }

        .paper-card.featured .paper-card-shell {
            display: grid;
            grid-template-columns: minmax(0, 1.4fr) minmax(290px, 0.8fr);
            gap: 18px;
            align-items: start;
        }

        .paper-card-main {
            display: flex;
            flex-direction: column;
            min-width: 0;
        }

        .paper-topline {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 12px;
            margin-bottom: 14px;
        }

        .paper-index {
            display: inline-flex;
            align-items: center;
            gap: 10px;
        }

        .paper-number {
            width: 36px;
            height: 36px;
            border-radius: 50%;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            background: rgba(184, 106, 69, 0.12);
            color: var(--accent-deep);
            font-size: 14px;
            font-weight: 700;
        }

        .paper-card.featured .paper-number {
            width: 42px;
            height: 42px;
            font-size: 15px;
            background: rgba(189, 106, 66, 0.14);
        }

        .recommendation-chip {
            padding: 8px 12px;
            border-radius: 999px;
            background: rgba(111, 123, 87, 0.12);
            color: var(--olive);
            font-size: 12px;
            font-weight: 700;
            letter-spacing: 0.04em;
            text-transform: uppercase;
        }

        .recommendation-chip.read-first {
            background: linear-gradient(180deg, rgba(189, 106, 66, 0.24), rgba(245, 220, 202, 0.92));
            color: #7a3820;
            border: 1px solid rgba(143, 75, 46, 0.22);
        }

        .recommendation-chip.skim {
            background: linear-gradient(180deg, rgba(184, 138, 56, 0.22), rgba(245, 234, 201, 0.92));
            color: #7b5a18;
            border: 1px solid rgba(148, 109, 33, 0.18);
        }

        .recommendation-chip.watch {
            background: linear-gradient(180deg, rgba(105, 115, 88, 0.22), rgba(227, 235, 216, 0.94));
            color: #445239;
            border: 1px solid rgba(86, 98, 69, 0.18);
        }

        .recommendation-chip.skip-for-now,
        .recommendation-chip.archive,
        .recommendation-chip.ignore {
            background: linear-gradient(180deg, rgba(129, 109, 94, 0.18), rgba(233, 225, 217, 0.92));
            color: #66584c;
            border: 1px solid rgba(120, 104, 91, 0.16);
        }

        .recommendation-chip.watchlist {
            background: linear-gradient(180deg, rgba(123, 104, 151, 0.18), rgba(233, 226, 242, 0.92));
            color: #5b4d75;
            border: 1px solid rgba(104, 90, 128, 0.16);
        }

        .recommendation-chip.unset {
            background: rgba(199, 186, 174, 0.28);
            color: #6d6259;
            border: 1px solid rgba(129, 109, 94, 0.14);
        }

        .score-badge {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 9px 12px;
            border-radius: 999px;
            font-size: 13px;
            font-weight: 700;
            border: 1px solid transparent;
            white-space: nowrap;
        }

        .score-badge.high {
            color: #6d3f26;
            background: rgba(222, 177, 141, 0.26);
            border-color: rgba(184, 106, 69, 0.22);
        }

        .score-badge.medium {
            color: #7a5c27;
            background: rgba(234, 214, 162, 0.34);
            border-color: rgba(188, 155, 80, 0.22);
        }

        .score-badge.low {
            color: #6d6259;
            background: rgba(199, 186, 174, 0.26);
            border-color: rgba(129, 109, 94, 0.18);
        }

        .paper-kicker {
            color: var(--accent-deep);
            font-size: 11px;
            letter-spacing: 0.09em;
            text-transform: uppercase;
            font-weight: 700;
            margin-bottom: 10px;
        }

        .paper-card h2 {
            font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif;
            font-size: clamp(25px, 3vw, 33px);
            line-height: 1.12;
            letter-spacing: -0.025em;
            margin-bottom: 10px;
            max-width: 24ch;
        }

        .paper-card h2 a {
            color: var(--ink);
            border-bottom: 1px solid transparent;
        }

        .paper-card h2 a:hover {
            color: var(--accent-deep);
            border-bottom-color: rgba(143, 77, 48, 0.25);
        }

        .paper-card.featured h2 {
            font-size: clamp(30px, 4vw, 42px);
            max-width: 22ch;
        }

        .paper-meta {
            display: flex;
            flex-wrap: wrap;
            gap: 10px 16px;
            color: var(--muted);
            font-size: 14px;
            margin-bottom: 14px;
        }

        .meta-item {
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }

        .meta-dot {
            width: 4px;
            height: 4px;
            border-radius: 50%;
            background: rgba(184, 106, 69, 0.65);
        }

        .tags {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-bottom: 16px;
        }

        .tag {
            padding: 7px 11px;
            border-radius: 999px;
            background: rgba(234, 212, 192, 0.58);
            color: #7a5846;
            font-size: 12px;
            font-weight: 600;
            border: 1px solid rgba(151, 110, 81, 0.12);
        }

        .lede {
            margin: 2px 0 16px;
            padding-left: 14px;
            border-left: 3px solid rgba(189, 106, 66, 0.35);
            color: var(--ink-soft);
            font-size: 15px;
        }

        .content-grid {
            display: grid;
            grid-template-columns: minmax(0, 1.28fr) minmax(270px, 0.72fr);
            gap: 16px;
            align-items: start;
        }

        .focus-panel,
        .side-panel {
            border-radius: 20px;
            border: 1px solid rgba(151, 110, 81, 0.12);
            background: rgba(255, 251, 245, 0.75);
        }

        .focus-panel {
            padding: 18px;
        }

        .focus-label {
            font-size: 12px;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: var(--accent-deep);
            font-weight: 700;
            margin-bottom: 8px;
        }

        .focus-copy {
            font-size: 15px;
            color: var(--ink-soft);
        }

        .focus-copy + .focus-label {
            margin-top: 16px;
        }

        .side-panel {
            padding: 16px;
            display: flex;
            flex-direction: column;
        }

        .score-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 10px;
            margin-bottom: 16px;
        }

        .score-cell {
            padding: 12px 10px;
            border-radius: 16px;
            background: rgba(245, 235, 224, 0.76);
            text-align: center;
            border: 1px solid rgba(151, 110, 81, 0.12);
            transition: transform 140ms ease, box-shadow 140ms ease;
        }

        .score-cell:hover {
            transform: translateY(-2px);
        }

        .score-k {
            font-size: 11px;
            color: var(--muted);
            text-transform: uppercase;
            letter-spacing: 0.08em;
            margin-bottom: 6px;
        }

        .score-v {
            font-family: "Iowan Old Style", "Palatino Linotype", Georgia, serif;
            font-size: 24px;
            color: var(--ink);
        }

        .score-note {
            margin-top: -2px;
            margin-bottom: 14px;
            color: var(--muted);
            font-size: 12px;
        }

        .section-label {
            color: var(--ink);
            font-size: 13px;
            font-weight: 700;
            margin-bottom: 8px;
        }

        .mini-list {
            margin-left: 18px;
            color: var(--ink-soft);
            font-size: 14px;
        }

        .mini-list li {
            margin-bottom: 7px;
        }

        .caution-list li {
            color: #8d5d49;
        }

        .neighbor-list {
            list-style: none;
            display: grid;
            gap: 8px;
            margin: 0 0 14px;
        }

        .neighbor-list li {
            padding: 9px 10px;
            border-radius: 12px;
            background: rgba(255, 248, 239, 0.72);
            border: 1px solid rgba(151, 110, 81, 0.1);
            color: var(--ink-soft);
            font-size: 13px;
            line-height: 1.35;
        }

        .neighbor-list strong {
            display: block;
            color: var(--ink);
            font-size: 13px;
            font-weight: 700;
            margin-bottom: 3px;
        }

        .neighbor-meta {
            display: block;
            color: var(--muted);
            font-size: 11px;
        }

        .neighbor-summary {
            color: var(--ink-soft);
            font-size: 13px;
            line-height: 1.5;
            margin: 0 0 14px;
        }

        details {
            margin-top: 16px;
            overflow: hidden;
            border-radius: 18px;
            border: 1px solid rgba(151, 110, 81, 0.08);
            background: rgba(255, 251, 245, 0.42);
            box-shadow: none;
            transition:
                background 160ms ease,
                border-color 160ms ease,
                box-shadow 160ms ease;
        }

        details[open] {
            border-color: rgba(151, 110, 81, 0.18);
            background: rgba(255, 251, 245, 0.82);
            box-shadow: 0 12px 28px rgba(98, 69, 46, 0.06);
        }

        summary {
            cursor: pointer;
            list-style: none;
            padding: 14px 18px;
            font-weight: 700;
            color: var(--accent-deep);
            user-select: none;
            transition: color 140ms ease, background 140ms ease;
        }

        details:not([open]) summary {
            background: rgba(255, 255, 255, 0.15);
        }

        details[open] summary {
            background: rgba(189, 106, 66, 0.06);
            border-bottom: 1px solid rgba(151, 110, 81, 0.12);
        }

        summary::-webkit-details-marker {
            display: none;
        }

        summary::after {
            content: "+";
            float: right;
            font-size: 22px;
            line-height: 1;
            color: rgba(143, 77, 48, 0.7);
        }

        details[open] summary::after {
            content: "-";
        }

        .abstract {
            padding: 14px 18px 18px;
            color: #43342c;
            font-size: 15px;
            font-weight: 500;
            line-height: 1.85;
        }

        .footer {
            text-align: center;
            margin-top: 30px;
            color: var(--muted);
            font-size: 13px;
        }

        @media (max-width: 1120px) {
            .paper-card.featured .paper-card-shell {
                grid-template-columns: 1fr;
            }

            .cards {
                grid-template-columns: 1fr;
            }

            .paper-card.featured {
                grid-column: auto;
            }
        }

        @media (max-width: 760px) {
            body {
                padding: 16px 12px 32px;
            }

            .hero {
                padding: 22px 18px 20px;
                border-radius: 24px;
            }

            .paper-card {
                padding: 18px;
                border-radius: 22px;
                min-height: 0;
                height: auto;
            }

            .paper-card-shell,
            .paper-card-main {
                flex: initial;
                min-height: 0;
                height: auto;
            }

            .paper-topline {
                flex-direction: column;
                align-items: stretch;
            }

            .hero-meta {
                gap: 8px;
            }

            .meta-pill {
                padding: 7px 10px;
                font-size: 11px;
            }

            .overview-band {
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 10px;
            }

            .overview-card {
                padding: 12px;
                border-radius: 16px;
            }

            .overview-label {
                font-size: 10px;
                margin-bottom: 4px;
            }

            .overview-value {
                font-size: 24px;
            }

            .overview-copy {
                font-size: 11px;
                line-height: 1.2;
            }

            .content-grid {
                grid-template-columns: 1fr;
            }

            .score-grid {
                grid-template-columns: repeat(3, 1fr);
            }

            details,
            details[open] {
                transition: none;
                box-shadow: none;
            }
        }
    """


def format_digest_html(candidates: list[dict], date_str: str) -> str:
    """Generate a self-contained HTML digest page for mobile viewing."""
    paper_count = len(candidates)
    recommendations = [
        str((candidate.get("review") or {}).get("recommendation") or "unset").replace("_", " ").title()
        for candidate in candidates
    ]
    read_first_count = sum(1 for item in recommendations if item == "Read First")
    skim_count = sum(1 for item in recommendations if item == "Skim")
    theme_count = len(
        {
            tag
            for candidate in candidates
            for tag in ((candidate.get("triage") or {}).get("matched_interest_labels") or [])
        }
    )
    display_date = html.escape(_display_date(date_str))

    cards_html = []
    for idx, candidate in enumerate(candidates, 1):
        paper = candidate["paper"]
        triage = candidate.get("triage", {})
        scores = candidate.get("_scores", {})
        review = candidate.get("review", {})

        title = html.escape(paper.get("title", "Untitled"))
        authors = paper.get("authors", [])
        author_line = html.escape(authors[0] + " et al." if len(authors) > 2 else ", ".join(authors[:2]))
        abstract_text = paper.get("abstract", "")
        abstract = html.escape(abstract_text)
        provider = str((candidate.get("source") or {}).get("provider") or "arxiv")
        provider_label = {
            "arxiv": "arXiv",
            "openalex": "OpenAlex",
            "semantic_scholar": "Semantic Scholar",
        }.get(provider, provider)
        display_id = paper.get("identifiers", {}).get("display") or paper.get("identifiers", {}).get("arxiv_id") or ""
        url = html.escape(paper.get("identifiers", {}).get("url", ""))

        total = scores.get("total", 0)
        map_match = scores.get("map_match", 0)
        zotero_semantic = scores.get("zotero_semantic", 0)
        score_class = "high" if total >= 0.7 else "medium" if total >= 0.5 else "low"

        tags = triage.get("matched_interest_labels", [])
        tags_html = "".join(f'<span class="tag">{html.escape(tag)}</span>' for tag in tags)

        recommendation_text = str(review.get("recommendation") or "unset").replace("_", " ").title()
        recommendation = html.escape(recommendation_text)
        recommendation_class = recommendation_text.lower().replace(" ", "-")

        why_text = review.get("why_it_matters") or "No recommendation note was written for this paper yet."
        reviewer_summary_text = review.get("reviewer_summary") or ""
        reviewer_summary = html.escape(reviewer_summary_text)
        quick_takeaways_html = _render_html_list(review.get("quick_takeaways") or [], "mini-list")
        caveats_html = _render_html_list(review.get("caveats") or [], "mini-list caution-list")
        semantic_neighbors = _neighbor_candidates(scores if isinstance(scores, dict) else {}, review if isinstance(review, dict) else {})
        neighbor_html = _render_neighbor_list(semantic_neighbors)
        neighbor_summary = _render_neighbor_summary(
            _neighbor_summary_text(scores if isinstance(scores, dict) else {}, review if isinstance(review, dict) else {})
        )
        lede = html.escape(why_text or reviewer_summary_text or abstract_text)
        feature_class = " featured" if idx == 1 else ""
        paper_kicker = "Featured route" if idx == 1 else f"Paper {idx}"

        card = f"""
        <div class="paper-card{feature_class}">
            <div class="paper-card-shell">
                <div class="paper-card-main">
                    <div class="paper-topline">
                        <div class="paper-index">
                            <span class="paper-number">{idx}</span>
                            <span class="recommendation-chip {recommendation_class}">{recommendation}</span>
                        </div>
                        <span class="score-badge {score_class}">{total:.2f} (M:{map_match:.2f} Z:{zotero_semantic:.2f})</span>
                    </div>
                    <p class="paper-kicker">{paper_kicker}</p>
                    <h2><a href="{url}" target="_blank">{title}</a></h2>
                    <div class="paper-meta">
                        <span class="meta-item">{author_line}</span>
                        <span class="meta-item"><span class="meta-dot"></span>{html.escape(provider_label)}{(": " + html.escape(display_id)) if display_id else ""}</span>
                    </div>
                    <div class="tags">{tags_html}</div>
                    <p class="lede">{lede}</p>
                    <div class="content-grid">
                        <div class="focus-panel">
                            {"<p class=\"focus-label\">Paper summary</p><p class=\"focus-copy\">" + reviewer_summary + "</p>" if reviewer_summary else "<p class=\"focus-label\">Paper summary</p><p class=\"focus-copy\">" + html.escape(abstract_text) + "</p>"}
                        </div>
                        <div class="side-panel">
                            <div class="score-grid">
                                <div class="score-cell" style="{_score_cell_style(total, 'total')}">
                                    <div class="score-k">Total</div>
                                    <div class="score-v">{total:.2f}</div>
                                </div>
                                <div class="score-cell" style="{_score_cell_style(map_match, 'map')}">
                                    <div class="score-k">Map</div>
                                    <div class="score-v">{map_match:.2f}</div>
                                </div>
                                <div class="score-cell" style="{_score_cell_style(zotero_semantic, 'zotero')}">
                                    <div class="score-k">Zotero</div>
                                    <div class="score-v">{zotero_semantic:.2f}</div>
                                </div>
                            </div>
                            <p class="score-note">Total score balances map alignment and Zotero semantic resonance.</p>
                            {"<p class=\"section-label\">Nearest Zotero</p>" + (neighbor_html or neighbor_summary) if (neighbor_html or neighbor_summary) else ""}
                            {"<p class=\"section-label\">Quick takeaways</p>" + quick_takeaways_html if quick_takeaways_html else ""}
                            {"<p class=\"section-label\">Caveats</p>" + caveats_html if caveats_html else ""}
                        </div>
                    </div>
                    <details>
                        <summary>Original abstract</summary>
                        <p class="abstract">{abstract}</p>
                    </details>
                </div>
            </div>
        </div>
        """
        cards_html.append(card)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Research Digest - {html.escape(date_str)}</title>
    <style>
        {_warm_page_css()}
    </style>
</head>
<body>
    <div class="page-shell">
        <div class="hero">
            <div class="eyebrow">Research Assist Digest</div>
            <h1>Research Digest</h1>
            <p class="hero-copy">Five papers, one clean reading route. Open the cards below and use the attachment when you want the full browser view.</p>
            <div class="hero-meta">
                <span class="meta-pill">{display_date}</span>
                <span class="meta-pill">{paper_count} selected</span>
                <span class="meta-pill">{theme_count} themes</span>
            </div>
        </div>
        <div class="overview-band">
            <div class="overview-card warm">
                <p class="overview-label">Selected</p>
                <div class="overview-value">{paper_count}</div>
                <p class="overview-copy">Kept picks</p>
            </div>
            <div class="overview-card olive">
                <p class="overview-label">Read First</p>
                <div class="overview-value">{read_first_count}</div>
                <p class="overview-copy">Start here</p>
            </div>
            <div class="overview-card">
                <p class="overview-label">Themes</p>
                <div class="overview-value">{theme_count}</div>
                <p class="overview-copy">Map lanes</p>
            </div>
            <div class="overview-card">
                <p class="overview-label">Signals</p>
                <div class="overview-value">2</div>
                <p class="overview-copy">Map + Zotero</p>
            </div>
        </div>
        <div class="cards">{''.join(cards_html)}</div>
        <div class="footer">
            Generated by research-assist
        </div>
    </div>
</body>
</html>"""


def format_search_html(papers: list[dict], query: str) -> str:
    """Generate HTML page for ad-hoc search results."""
    paper_count = len(papers)

    cards_html = []
    for idx, paper in enumerate(papers, 1):
        title = html.escape(paper.get("title", "Untitled"))
        authors = paper.get("authors", [])
        author_line = html.escape(authors[0] + " et al." if len(authors) > 2 else ", ".join(authors[:2]))
        summary_text = paper.get("summary", "")
        summary = html.escape(summary_text)
        summary_preview = html.escape(_truncate(summary_text, 170))
        url = html.escape(paper.get("html_url", ""))
        provider = str(paper.get("provider") or "arxiv")
        provider_label = {
            "arxiv": "arXiv",
            "openalex": "OpenAlex",
            "semantic_scholar": "Semantic Scholar",
        }.get(provider, provider)
        display_id = html.escape(str(paper.get("paper_id_display") or paper.get("arxiv_id") or ""))
        feature_class = " featured" if idx == 1 else ""

        card = f"""
        <div class="paper-card{feature_class}">
            <div class="paper-card-shell">
                <div class="paper-card-main">
                    <div class="paper-topline">
                        <div class="paper-index">
                            <span class="paper-number">{idx}</span>
                            <span class="recommendation-chip">Search hit</span>
                        </div>
                    </div>
                    <p class="paper-kicker">Search result</p>
                    <h2><a href="{url}" target="_blank">{title}</a></h2>
                    <div class="paper-meta">
                        <span class="meta-item">{author_line}</span>
                        <span class="meta-item"><span class="meta-dot"></span>{html.escape(provider_label)}{(": " + display_id) if display_id else ""}</span>
                    </div>
                    <p class="lede">{summary_preview}</p>
                    <details>
                        <summary>Original abstract</summary>
                        <p class="abstract">{summary}</p>
                    </details>
                </div>
            </div>
        </div>
        """
        cards_html.append(card)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Search Results - {html.escape(query)}</title>
    <style>
        {_warm_page_css()}
    </style>
</head>
<body>
    <div class="page-shell">
        <div class="hero">
            <div class="eyebrow">Research Assist Search</div>
            <h1>Search Results</h1>
            <p class="hero-copy">A compact search view for quick triage. Open the strongest hits and skip the rest.</p>
            <div class="hero-meta">
                <span class="meta-pill">Query: {html.escape(query)}</span>
                <span class="meta-pill">{paper_count} papers</span>
            </div>
        </div>
        <div class="cards">{''.join(cards_html)}</div>
        <div class="footer">
            Generated by research-assist
        </div>
    </div>
</body>
</html>"""
