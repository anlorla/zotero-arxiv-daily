import html
import re
from datetime import datetime

from .protocol import Paper, TLDR_LABELS

# Chinese-friendly, email-client-safe font stack (inline everywhere because
# Gmail and many clients strip <head><style>). NOTE: must use single quotes —
# these strings live inside style="..." attributes, so a double quote would
# terminate the attribute early and silently kill every style after it.
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', Arial, sans-serif"

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
"""

# 6P 速读各维度在邮件里的副标题（标签本身保持英文）
LABEL_HINTS = {
    "Problem": "瓶颈",
    "Premise": "假设",
    "Perturbation": "改动",
    "Principle": "机理",
    "Proof": "证据",
    "Push": "延伸",
}

_LABEL_RE = re.compile(rf"^({'|'.join(TLDR_LABELS)})\s*[:：]\s*(.*)$")


def parse_tldr_sections(tldr: str) -> list[tuple[str, str]] | None:
    """Split a plain-text 6P TLDR into (label, content) pairs.

    Returns None when the text does not follow the labeled format (e.g. the
    raw-abstract fallback), in which case the caller renders it as a plain
    paragraph instead.
    """
    if not tldr:
        return None
    sections: list[list[str]] = []
    for line in tldr.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _LABEL_RE.match(line)
        if m:
            sections.append([m.group(1), m.group(2).strip()])
        elif sections:
            # continuation of the previous section
            sections[-1][1] = (sections[-1][1] + " " + line).strip()
    sections = [(label, content) for label, content in sections if content]
    if len(sections) < 2:
        return None
    return sections


def get_header_html(count: int) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    return f"""
    <tr>
      <td style="padding:4px 4px 18px 4px; font-family:{FONT};">
        <div style="font-size:22px; font-weight:700; color:#1a1a1a;">📚 今日 arXiv 精选</div>
        <div style="font-size:13px; color:#8a8f98; margin-top:6px;">{today} · {count} 篇过线论文 · 按相关度排序 · 6P 速读</div>
      </td>
    </tr>
    """


def get_footer_html() -> str:
    return f"""
    <tr>
      <td style="padding:18px 4px 4px 4px; font-family:{FONT}; font-size:12px; color:#a0a4ab; line-height:1.6;">
        基于你的 Zotero 文库相似度推荐 · 只保留相关度达标的论文（不足额是正常现象）。<br>
        调整门槛/篇数：改仓库 config/base.yaml 的 min_score / max_paper_num。
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
              今天没有过线的新论文，歇一歇 ☕
            </td>
          </tr>
        </table>
      </td>
    </tr>
    """


def get_relevance_pill(score: float | None) -> str:
    """A compact colored pill showing the relevance score, tinted by tier."""
    if score is None:
        return (
            f'<span style="display:inline-block; font-family:{FONT}; font-size:12px; '
            f'font-weight:600; color:#8a8f98; background-color:#f0f1f3; padding:4px 10px; '
            f'border-radius:999px; white-space:nowrap;">相关度未知</span>'
        )
    if score >= 5.0:
        bg, fg = "#e7f6ec", "#1a7f37"
    elif score >= 4.6:
        bg, fg = "#e8f0fe", "#1a56c4"
    else:
        bg, fg = "#fff4e0", "#9a6700"
    return (
        f'<span style="display:inline-block; font-family:{FONT}; font-size:12px; '
        f'font-weight:700; color:{fg}; background-color:{bg}; padding:4px 12px; '
        f'border-radius:999px; white-space:nowrap;">相关度 {score:.1f}</span>'
    )


def get_tldr_html(tldr: str | None) -> str:
    """Render the 6P TLDR box. Falls back to a plain paragraph when the text
    is not in the labeled format (e.g. the raw-abstract fallback)."""
    sections = parse_tldr_sections(tldr or "")
    if sections is None:
        body = html.escape(tldr or "暂无摘要")
        return f"""
              <div style="font-family:{FONT}; font-size:13.5px; color:#5a5f66; line-height:1.7; background-color:#f7f8fa; border-radius:10px; padding:14px 16px; margin-top:14px;">
                <div style="font-size:11px; font-weight:700; color:#9aa0a8; letter-spacing:0.4px; margin-bottom:6px;">原文摘要（速读生成失败）</div>
                {body}
              </div>"""

    rows = []
    for label, content in sections:
        hint = LABEL_HINTS.get(label, "")
        rows.append(f"""
                <tr>
                  <td style="vertical-align:top; padding:7px 14px 7px 0; white-space:nowrap;">
                    <span style="font-family:{FONT}; font-size:12.5px; font-weight:700; color:#4956d4;">{html.escape(label)}</span>
                    <span style="font-family:{FONT}; font-size:11px; color:#9aa0a8;"> {hint}</span>
                  </td>
                  <td style="vertical-align:top; padding:7px 0; font-family:{FONT}; font-size:14px; color:#2c2f33; line-height:1.7; width:100%;">{html.escape(content)}</td>
                </tr>""")
    return f"""
              <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color:#f7f8fb; border-left:3px solid #4956d4; border-radius:0 10px 10px 0; margin-top:14px;">
                <tr><td style="padding:8px 16px;">
                  <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">{''.join(rows)}
                  </table>
                </td></tr>
              </table>"""


def get_block_html(rank: int, title: str, url: str, authors: str, rate_html: str,
                   tldr: str, pdf_url: str, affiliations: str = None) -> str:
    rank_badge = (
        f'<span style="display:inline-block; min-width:24px; height:24px; line-height:24px; '
        f'text-align:center; background-color:#1a1a1a; color:#ffffff; font-size:13px; '
        f'font-weight:700; border-radius:6px; padding:0 6px;">{rank}</span>'
    )
    title_link = url or pdf_url
    affiliation_html = ""
    if affiliations:
        affiliation_html = (
            f'<div style="font-family:{FONT}; font-size:12.5px; color:#9aa0a8; margin-top:4px;">'
            f'{html.escape(affiliations)}</div>'
        )
    pdf_button = ""
    if pdf_url:
        pdf_button = (
            f'<a href="{html.escape(pdf_url, quote=True)}" style="display:inline-block; text-decoration:none; '
            f'font-family:{FONT}; font-size:13px; font-weight:600; color:#ffffff; '
            f'background-color:#b31b1b; padding:9px 18px; border-radius:8px;">阅读 PDF</a>'
        )
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
                    <a href="{html.escape(title_link or '', quote=True)}" style="font-family:{FONT}; font-size:17px; font-weight:700; color:#1a1a1a; text-decoration:none; line-height:1.45;">{html.escape(title)}</a>
                  </td>
                  <td style="vertical-align:top; padding-left:10px;">{rate_html}</td>
                </tr>
              </table>

              <div style="font-family:{FONT}; font-size:13px; color:#6b7079; margin-top:10px; line-height:1.5;">{html.escape(authors)}</div>
              {affiliation_html}

              {get_tldr_html(tldr)}

              <div style="margin-top:16px;">
                {pdf_button}
                <a href="{html.escape(title_link or '', quote=True)}" style="display:inline-block; text-decoration:none; font-family:{FONT}; font-size:13px; font-weight:600; color:#3a3f47; background-color:#eef0f3; padding:9px 18px; border-radius:8px; margin-left:8px;">arXiv 页面</a>
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
            affiliations = None  # 提取失败就干脆不显示，比"机构未知"干净
        parts.append(get_block_html(rank, p.title, p.url, authors, rate_html, p.tldr, p.pdf_url, affiliations))

    parts.append(get_footer_html())
    content = ''.join(parts)
    return framework.replace('__CONTENT__', content)
