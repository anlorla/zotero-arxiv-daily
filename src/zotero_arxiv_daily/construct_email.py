from .protocol import Paper

# Chinese-friendly, email-client-safe font stack (inline everywhere because
# Gmail and many clients strip <head><style>).
FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", Arial, sans-serif'

framework = """
<!DOCTYPE HTML>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0; padding:0; background-color:#f4f5f7;">
  <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color:#f4f5f7;">
    <tr>
      <td align="center" style="padding:24px 12px;">
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width:680px; margin:0 auto;">
          __CONTENT__
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
""".replace("{FONT}", FONT)


def get_header_html(count: int) -> str:
    return f"""
    <tr>
      <td style="padding:4px 4px 18px 4px; font-family:{FONT};">
        <div style="font-size:22px; font-weight:700; color:#1a1a1a;">📚 今日 arXiv 精选</div>
        <div style="font-size:13px; color:#8a8f98; margin-top:6px;">为你筛选出 {count} 篇高相关论文 · 按相关度排序</div>
      </td>
    </tr>
    """


def get_footer_html() -> str:
    return f"""
    <tr>
      <td style="padding:18px 4px 4px 4px; font-family:{FONT}; font-size:12px; color:#a0a4ab; line-height:1.6;">
        基于你的 Zotero 文库相似度推荐。想退订或调整，请在 GitHub Action 设置里修改。
      </td>
    </tr>
    """


def get_empty_html() -> str:
    return f"""
    <tr>
      <td style="padding:0;">
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="border:1px solid #e6e8eb; border-radius:14px; background-color:#ffffff;">
          <tr>
            <td style="padding:28px; font-family:{FONT}; font-size:18px; font-weight:600; color:#1a1a1a; text-align:center;">
              今天没有匹配的新论文，歇一歇 ☕
            </td>
          </tr>
        </table>
      </td>
    </tr>
    """


def get_relevance_pill(score: float) -> str:
    """A compact pill with a 0-5 star bar plus the raw score, colored by tier."""
    if score is None:
        return f'<span style="font-family:{FONT}; font-size:12px; color:#8a8f98;">相关度未知</span>'

    # Map the score to 0-5 stars over a sensible window (the reranker score is
    # roughly 10 * weighted cosine similarity).
    low, high = 4.0, 7.0
    ratio = max(0.0, min(1.0, (score - low) / (high - low)))
    filled = round(ratio * 5)
    stars = (
        '<span style="color:#f5a623;">' + '★' * filled + '</span>'
        + '<span style="color:#dcdfe4;">' + '★' * (5 - filled) + '</span>'
    )

    if score >= 5.5:
        bg, fg = "#e7f6ec", "#1a7f37"
    elif score >= 4.8:
        bg, fg = "#e8f0fe", "#1a56c4"
    else:
        bg, fg = "#fef3e6", "#b46a14"

    return (
        f'<span style="display:inline-block; font-family:{FONT}; font-size:12px; '
        f'font-weight:600; color:{fg}; background-color:{bg}; padding:4px 10px; '
        f'border-radius:999px; white-space:nowrap;">{stars}&nbsp;&nbsp;相关度 {score:.1f}</span>'
    )


def get_block_html(rank: int, title: str, url: str, authors: str, rate_html: str,
                   tldr: str, pdf_url: str, affiliations: str = None) -> str:
    rank_badge = (
        f'<span style="display:inline-block; min-width:24px; height:24px; line-height:24px; '
        f'text-align:center; background-color:#1a1a1a; color:#ffffff; font-size:13px; '
        f'font-weight:700; border-radius:6px; padding:0 6px;">{rank}</span>'
    )
    title_link = url or pdf_url
    block_template = f"""
    <tr>
      <td style="padding:0 0 16px 0;">
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="border:1px solid #e6e8eb; border-radius:14px; background-color:#ffffff;">
          <tr>
            <td style="padding:20px 22px;">

              <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
                <tr>
                  <td style="vertical-align:top; padding-right:10px;">{rank_badge}</td>
                  <td style="vertical-align:top; width:100%;">
                    <a href="{title_link}" style="font-family:{FONT}; font-size:18px; font-weight:700; color:#1a1a1a; text-decoration:none; line-height:1.4;">{title}</a>
                  </td>
                </tr>
              </table>

              <div style="font-family:{FONT}; font-size:13px; color:#6b7079; margin-top:10px; line-height:1.5;">
                {authors}<br>
                <span style="color:#9aa0a8; font-style:italic;">{affiliations}</span>
              </div>

              <div style="margin-top:12px;">{rate_html}</div>

              <div style="font-family:{FONT}; font-size:14px; color:#2c2f33; line-height:1.75; background-color:#f7f8fa; border-radius:10px; padding:14px 16px; margin-top:14px;">
                {tldr}
              </div>

              <div style="margin-top:16px;">
                <a href="{pdf_url}" style="display:inline-block; text-decoration:none; font-family:{FONT}; font-size:13px; font-weight:600; color:#ffffff; background-color:#d9534f; padding:9px 18px; border-radius:8px;">阅读 PDF</a>
                <a href="{title_link}" style="display:inline-block; text-decoration:none; font-family:{FONT}; font-size:13px; font-weight:600; color:#3a3f47; background-color:#eef0f3; padding:9px 18px; border-radius:8px; margin-left:8px;">arXiv 页面</a>
              </div>

            </td>
          </tr>
        </table>
      </td>
    </tr>
    """
    return block_template


def render_email(papers: list[Paper]) -> str:
    if len(papers) == 0:
        content = get_header_html(0) + get_empty_html() + get_footer_html()
        return framework.replace('__CONTENT__', content)

    parts = [get_header_html(len(papers))]
    for rank, p in enumerate(papers, start=1):
        rate_html = get_relevance_pill(p.score)
        author_list = [a for a in p.authors]
        num_authors = len(author_list)
        if num_authors <= 5:
            authors = ', '.join(author_list)
        else:
            authors = ', '.join(author_list[:3] + ['...'] + author_list[-2:])
        if p.affiliations is not None and len(p.affiliations) > 0:
            affiliations = ', '.join(p.affiliations[:5])
            if len(p.affiliations) > 5:
                affiliations += ', ...'
        else:
            affiliations = '机构未知'
        parts.append(get_block_html(rank, p.title, p.url, authors, rate_html, p.tldr, p.pdf_url, affiliations))

    parts.append(get_footer_html())
    content = ''.join(parts)
    return framework.replace('__CONTENT__', content)
