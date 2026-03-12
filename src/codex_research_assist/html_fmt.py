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

        .hero-grid {
            display: grid;
            grid-template-columns: minmax(0, 1.45fr) minmax(300px, 0.85fr);
            gap: 20px;
            align-items: stretch;
        }

        .hero-copy-panel {
            position: relative;
            z-index: 1;
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
            margin-bottom: 22px;
        }

        .hero-meta {
            display: flex;
            flex-wrap: wrap;
            gap: 12px;
        }

        .meta-pill {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 10px 14px;
            border-radius: 999px;
            background: rgba(255, 251, 246, 0.78);
            border: 1px solid rgba(151, 110, 81, 0.11);
            color: var(--ink-soft);
            font-size: 13px;
        }

        .hero-route {
            position: relative;
            z-index: 1;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            gap: 18px;
            border-radius: 26px;
            border: 1px solid rgba(151, 110, 81, 0.14);
            background:
                linear-gradient(180deg, rgba(255, 251, 245, 0.94), rgba(246, 235, 224, 0.92));
            padding: 20px;
            box-shadow: var(--shadow-soft);
        }

        .route-kicker {
            font-size: 12px;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: var(--accent-deep);
            font-weight: 700;
            margin-bottom: 8px;
        }

        .route-title {
            font-family: "Iowan Old Style", "Palatino Linotype", Georgia, serif;
            font-size: 27px;
            line-height: 1.08;
            margin-bottom: 8px;
        }

        .route-copy {
            color: var(--ink-soft);
            font-size: 14px;
        }

        .route-list {
            list-style: none;
            display: grid;
            gap: 10px;
        }

        .route-item {
            display: grid;
            grid-template-columns: 24px 1fr;
            gap: 10px;
            align-items: start;
            color: var(--ink-soft);
            font-size: 14px;
        }

        .route-item strong {
            color: var(--ink);
            font-weight: 700;
        }

        .route-index {
            width: 24px;
            height: 24px;
            border-radius: 50%;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            background: var(--accent-soft);
            color: var(--accent-deep);
            font-size: 12px;
            font-weight: 700;
        }

        .overview-band {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 14px;
            margin-bottom: 22px;
        }

        .overview-card {
            border-radius: 22px;
            padding: 18px;
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
            margin-bottom: 8px;
            font-weight: 700;
        }

        .overview-value {
            font-family: "Iowan Old Style", "Palatino Linotype", Georgia, serif;
            font-size: clamp(28px, 4vw, 42px);
            line-height: 1;
            margin-bottom: 8px;
        }

        .overview-copy {
            color: var(--ink-soft);
            font-size: 14px;
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
            background: rgba(189, 106, 66, 0.14);
            color: var(--accent-deep);
        }

        .recommendation-chip.skim {
            background: rgba(184, 138, 56, 0.14);
            color: #8d6928;
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
        .side-panel,
        details {
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

        details {
            margin-top: 16px;
            overflow: hidden;
        }

        summary {
            cursor: pointer;
            list-style: none;
            padding: 14px 18px;
            font-weight: 700;
            color: var(--accent-deep);
            user-select: none;
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
            padding: 0 18px 18px;
            color: var(--ink-soft);
            font-size: 14px;
            line-height: 1.78;
        }

        .footer {
            text-align: center;
            margin-top: 30px;
            color: var(--muted);
            font-size: 13px;
        }

        @media (max-width: 1120px) {
            .hero-grid,
            .paper-card.featured .paper-card-shell {
                grid-template-columns: 1fr;
            }

            .overview-band {
                grid-template-columns: repeat(2, minmax(0, 1fr));
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
            }

            .paper-topline {
                flex-direction: column;
                align-items: stretch;
            }

            .overview-band {
                grid-template-columns: 1fr;
            }

            .content-grid {
                grid-template-columns: 1fr;
            }

            .score-grid {
                grid-template-columns: repeat(3, 1fr);
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

    if candidates:
        lead_paper = candidates[0]["paper"]
        lead_review = candidates[0].get("review") or {}
        lead_title = html.escape(lead_paper.get("title", "Untitled"))
        lead_reason = html.escape(
            _truncate(
                lead_review.get("why_it_matters")
                or lead_review.get("reviewer_summary")
                or lead_paper.get("abstract", ""),
                150,
            )
        )
    else:
        lead_title = "No papers selected"
        lead_reason = "The digest did not contain any candidate papers."

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
        arxiv_id = paper.get("identifiers", {}).get("arxiv_id", "")
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
        why_it_matters = html.escape(why_text)
        reviewer_summary_text = review.get("reviewer_summary") or ""
        reviewer_summary = html.escape(reviewer_summary_text)
        quick_takeaways_html = _render_html_list(review.get("quick_takeaways") or [], "mini-list")
        caveats_html = _render_html_list(review.get("caveats") or [], "mini-list caution-list")
        lede = html.escape(_truncate(why_text or reviewer_summary_text or abstract_text, 165))
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
                        <span class="meta-item"><span class="meta-dot"></span>arXiv: {html.escape(arxiv_id)}</span>
                    </div>
                    <div class="tags">{tags_html}</div>
                    <p class="lede">{lede}</p>
                    <div class="content-grid">
                        <div class="focus-panel">
                            <p class="focus-label">Why it matters</p>
                            <p class="focus-copy">{why_it_matters}</p>
                            {"<p class=\"focus-label\">Paper summary</p><p class=\"focus-copy\">" + reviewer_summary + "</p>" if reviewer_summary else ""}
                        </div>
                        <div class="side-panel">
                            <div class="score-grid">
                                <div class="score-cell">
                                    <div class="score-k">Total</div>
                                    <div class="score-v">{total:.2f}</div>
                                </div>
                                <div class="score-cell">
                                    <div class="score-k">Map</div>
                                    <div class="score-v">{map_match:.2f}</div>
                                </div>
                                <div class="score-cell">
                                    <div class="score-k">Zotero</div>
                                    <div class="score-v">{zotero_semantic:.2f}</div>
                                </div>
                            </div>
                            <p class="score-note">Total score balances map alignment and Zotero semantic resonance.</p>
                            {"<p class=\"section-label\">Quick takeaways</p>" + quick_takeaways_html if quick_takeaways_html else ""}
                            {"<p class=\"section-label\">Caveats</p>" + caveats_html if caveats_html else ""}
                        </div>
                    </div>
                    <details>
                        <summary>Original arXiv abstract</summary>
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
            <div class="hero-grid">
                <div class="hero-copy-panel">
                    <div class="eyebrow">Research Assist Digest</div>
                    <h1>Research Digest</h1>
                    <p class="hero-copy">A warmer, more editorial reading surface for your shortlist: map-aligned signals, Zotero resonance, and concrete reasons to care, arranged like a research notebook rather than a dashboard.</p>
                    <div class="hero-meta">
                        <span class="meta-pill">{html.escape(date_str)}</span>
                        <span class="meta-pill">{paper_count} papers selected</span>
                        <span class="meta-pill">{theme_count} active themes</span>
                    </div>
                </div>
                <aside class="hero-route">
                    <div>
                        <p class="route-kicker">Reading route</p>
                        <h2 class="route-title">Start with the papers that actually move your map.</h2>
                        <p class="route-copy">This digest now treats the shortlist like a route: a featured lead, then supporting branches, then lower-priority references.</p>
                    </div>
                    <ol class="route-list">
                        <li class="route-item"><span class="route-index">1</span><span><strong>{lead_title}</strong><br>{lead_reason}</span></li>
                        <li class="route-item"><span class="route-index">2</span><span><strong>{read_first_count} read-first papers</strong><br>These are the closest bets for immediate reading and note-taking.</span></li>
                        <li class="route-item"><span class="route-index">3</span><span><strong>{skim_count} skim papers</strong><br>These are still useful, but more for boundary checking or branch expansion.</span></li>
                    </ol>
                </aside>
            </div>
        </div>
        <div class="overview-band">
            <div class="overview-card warm">
                <p class="overview-label">Selected</p>
                <div class="overview-value">{paper_count}</div>
                <p class="overview-copy">Final papers kept in this digest after ranking and selection.</p>
            </div>
            <div class="overview-card olive">
                <p class="overview-label">Read First</p>
                <div class="overview-value">{read_first_count}</div>
                <p class="overview-copy">High-priority papers that most likely deserve immediate attention.</p>
            </div>
            <div class="overview-card">
                <p class="overview-label">Themes</p>
                <div class="overview-value">{theme_count}</div>
                <p class="overview-copy">Distinct profile branches touched by the current shortlist.</p>
            </div>
            <div class="overview-card">
                <p class="overview-label">Signals</p>
                <div class="overview-value">2</div>
                <p class="overview-copy">Every card balances map alignment and Zotero semantic resonance.</p>
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
        arxiv_id = html.escape(paper.get("arxiv_id", ""))
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
                        <span class="meta-item"><span class="meta-dot"></span>arXiv: {arxiv_id}</span>
                    </div>
                    <p class="lede">{summary_preview}</p>
                    <details>
                        <summary>Original arXiv abstract</summary>
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
            <div class="hero-grid">
                <div class="hero-copy-panel">
                    <div class="eyebrow">Research Assist Search</div>
                    <h1>Search Results</h1>
                    <p class="hero-copy">A denser reading layout for ad-hoc arXiv exploration, using the same warm editorial surface as the digest while giving the first result stronger emphasis.</p>
                    <div class="hero-meta">
                        <span class="meta-pill">Query: {html.escape(query)}</span>
                        <span class="meta-pill">{paper_count} papers</span>
                    </div>
                </div>
                <aside class="hero-route">
                    <div>
                        <p class="route-kicker">Search view</p>
                        <h2 class="route-title">Scan faster, then open the few that matter.</h2>
                        <p class="route-copy">This layout uses a featured first result, wider cards, and more compact summaries so the page carries more signal per screen.</p>
                    </div>
                    <ol class="route-list">
                        <li class="route-item"><span class="route-index">1</span><span><strong>Featured first hit</strong><br>The first result gets the strongest visual emphasis for rapid triage.</span></li>
                        <li class="route-item"><span class="route-index">2</span><span><strong>Compact previews</strong><br>Every card shows a visible lede before the expandable abstract.</span></li>
                        <li class="route-item"><span class="route-index">3</span><span><strong>Two-column flow</strong><br>Desktop space is used more aggressively, while mobile still collapses cleanly.</span></li>
                    </ol>
                </aside>
            </div>
        </div>
        <div class="cards">{''.join(cards_html)}</div>
        <div class="footer">
            Generated by research-assist
        </div>
    </div>
</body>
</html>"""
