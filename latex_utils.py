"""High-grade LaTeX generator and Tectonic compiler for ATS-optimized resumes.

Produces publication-grade, Overleaf-compatible LaTeX documents using the industry-standard
Jake's Resume / Overleaf structure:
- Mathematical spacing and strict margin control
- Full ATS-parsability with standard vector fonts
- Clickable hyperref links for emails, LinkedIn, and GitHub
- Native section rules, bold emphasis, and bullet formatting
- Direct, offline compilation via Tectonic (< 0.5s)
"""

import os
import re
import shutil
import subprocess
import unicodedata
from typing import Optional


def _clean_glyphs(text: str) -> str:
    """Normalize unicode and replace non-ASCII characters with standard ASCII equivalents."""
    if not text:
        return ""
    # Clean common UTF-8 decoding mojibake
    text = text.replace("‚Äî", "-").replace("‚Üí", "->").replace("‚â•", ">=")
    text = text.replace("â€\"", "-").replace("â†'", "->").replace("â†’", "->").replace("â‰¥", ">=")
    text = text.replace("â€“", "-").replace("â€™", "'").replace("â€œ", '"').replace("â€\x9d", '"')

    text = unicodedata.normalize("NFKD", text)
    # Replace unicode hyphens and dashes
    text = re.sub(r"[\u2010\u2011\u2012\u2013\u2014\u2015\u2212\u00ad]", "-", text)
    # Replace unicode spaces
    text = re.sub(r"[\u00a0\u2000-\u200b\u202f\u205f\u3000]", " ", text)
    # Replace quotes
    text = re.sub(r"[\u2018\u2019\u201a\u201b]", "'", text)
    text = re.sub(r"[\u201c\u201d\u201e\u201f]", '"', text)
    # Replace math and arrows
    text = text.replace("→", "->").replace("←", "<-").replace("⇒", "=>")
    text = text.replace("×", "x").replace("≈", "~").replace("≥", ">=").replace("≤", "<=")
    text = text.replace("Δ-", "Delta-").replace("Δ", "Delta ")
    return text


def is_meta_commentary(text: str) -> bool:
    """Detect and ignore LLM meta-commentary, footers, disclaimers, or compilation notes."""
    if not text:
        return False
    t = _clean_glyphs(text).strip().lower()
    t = re.sub(r"^[*_`#\s]+|[*_`#\s]+$", "", t)
    meta_patterns = [
        r"this resume is formatted to fit",
        r"formatted to fit a single page",
        r"fit onto exactly one page",
        r"fit cleanly onto",
        r"compiled with latex",
        r"compiled with tectonic",
        r"^note:\s+",
        r"^disclaimer:",
        r"^prepared for\b",
        r"target exactly 1 page",
        r"1-page budget",
    ]
    return any(re.search(pat, t) for pat in meta_patterns)


def escape_latex(text: str) -> str:
    """Safely escape LaTeX special characters in plain text while keeping ASCII clean."""
    if not text:
        return ""
    text = _clean_glyphs(text)
    # Normalize percent spacing: "92.7 %" -> "92.7%"
    text = re.sub(r"(\d+(?:\.\d+)?)\s+%", r"\1%", text)
    # Escape backslashes first if any
    text = text.replace("\\", "\\textbackslash{}")
    # Escape standard LaTeX reserved characters
    chars_to_escape = {
        "&": "\\&",
        "%": "\\%",
        "$": "\\$",
        "#": "\\#",
        "_": "\\_",
        "{": "\\{",
        "}": "\\}",
        "~": "\\textasciitilde{}",
        "^": "\\textasciicircum{}",
    }
    for char, replacement in chars_to_escape.items():
        text = text.replace(char, replacement)
    return text


def format_inline_latex(text: str) -> str:
    """Convert inline Markdown styling (bold, italic, links, code) into valid LaTeX."""
    if not text:
        return ""

    text = _clean_glyphs(text)
    # Normalize percent spacing: "92.7 %" -> "92.7%"
    text = re.sub(r"(\d+(?:\.\d+)?)\s+%", r"\1%", text)

    # 1. Protect markdown links [label](url)
    md_links = []
    def md_link_sub(m):
        idx = len(md_links)
        md_links.append((m.group(1), m.group(2)))
        return f"XXMDLINK{idx}XX"
    text = re.sub(r"\[([^\]]+)\]\((https?://[^\)]+)\)", md_link_sub, text)

    # 2. Protect raw angle-bracket links <url>
    raw_links = []
    def raw_link_sub(m):
        idx = len(raw_links)
        raw_links.append(m.group(1))
        return f"XXRAWURL{idx}XX"
    text = re.sub(r"<(https?://[^>]+)>", raw_link_sub, text)

    # 2.5 Protect naked URLs before bold/italic or text escaping
    naked_urls = []
    def naked_url_sub(m):
        idx = len(naked_urls)
        naked_urls.append(m.group(0))
        return f"XXNAKEDURL{idx}XX"
    text = re.sub(r"https?://[^\s)\]\"'>]+", naked_url_sub, text)

    # 3. Protect inline code `code`
    code_blocks = []
    def code_sub(m):
        idx = len(code_blocks)
        code_blocks.append(m.group(1))
        return f"XXCODE{idx}XX"
    text = re.sub(r"`([^`]+)`", code_sub, text)

    # 4. Protect markdown bold **text** and italic *text* before escaping
    bolds = []
    def bold_sub(m):
        idx = len(bolds)
        bolds.append(m.group(1))
        return f"XXBOLD{idx}XX"
    text = re.sub(r"\*\*([^*]+)\*\*", bold_sub, text)

    italics = []
    def italic_sub(m):
        idx = len(italics)
        italics.append(m.group(1))
        return f"XXITALIC{idx}XX"
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", italic_sub, text)

    # 5. Escape general text
    text = escape_latex(text)

    # 6. Restore bold
    for idx, content in enumerate(bolds):
        text = text.replace(f"XXBOLD{idx}XX", f"\\textbf{{{format_inline_latex(content)}}}")

    # 7. Restore italic
    for idx, content in enumerate(italics):
        text = text.replace(f"XXITALIC{idx}XX", f"\\textit{{{format_inline_latex(content)}}}")

    # 8. Restore code blocks
    for idx, content in enumerate(code_blocks):
        escaped_code = escape_latex(content)
        text = text.replace(f"XXCODE{idx}XX", f"\\textbf{{{escaped_code}}}")

    # 9. Restore markdown links
    for idx, (label, url) in enumerate(md_links):
        safe_label = escape_latex(label)
        clean_url = url.replace("%", "\\%")
        text = text.replace(f"XXMDLINK{idx}XX", f"\\href{{{clean_url}}}{{\\underline{{{safe_label}}}}}")

    # 10. Restore raw links
    for idx, url in enumerate(raw_links):
        clean_url = url.replace("%", "\\%")
        display = url.replace("https://", "").replace("http://", "").rstrip("/")
        safe_display = escape_latex(display)
        text = text.replace(f"XXRAWURL{idx}XX", f"\\href{{{clean_url}}}{{\\underline{{{safe_display}}}}}")

    # 11. Restore naked URLs
    for idx, url in enumerate(naked_urls):
        clean_url = url.replace("%", "\\%")
        display = url.replace("https://", "").replace("http://", "").rstrip("/")
        safe_display = escape_latex(display)
        text = text.replace(f"XXNAKEDURL{idx}XX", f"\\href{{{clean_url}}}{{\\underline{{{safe_display}}}}}")

    return text


def markdown_to_latex(markdown_text: str) -> str:
    """Convert a resume in Markdown format into a complete, high-grade LaTeX document."""
    raw_lines = markdown_text.splitlines()
    lines = [l.strip() for l in raw_lines]
    total = len(lines)
    i = 0

    candidate_name = "Candidate Name"
    contact_entries = []

    # 1. Parse Name
    while i < total and not lines[i]:
        i += 1

    if i < total:
        line_candidate = lines[i]
        if line_candidate.startswith("#"):
            candidate_name = re.sub(r"^#+\s*", "", line_candidate).strip()
            candidate_name = re.sub(r"^\*\*([^*]+)\*\*$", r"\1", candidate_name).strip()
            i += 1
        elif not any(k in line_candidate.lower() for k in ["email", "phone", "linkedin", "github", "http", "@"]) and line_candidate != "---":
            candidate_name = re.sub(r"^\*\*([^*]+)\*\*$", r"\1", line_candidate).strip()
            candidate_name = candidate_name.strip("#* ")
            i += 1

    # 2. Parse Contact Block
    while i < total:
        line = lines[i]
        if not line or line == "---" or line.startswith("#"):
            break
        clean_c = _clean_glyphs(line)
        # Split tokens by pipe
        tokens = [t.strip() for t in clean_c.split("|") if t.strip()]
        for tok in tokens:
            tok_clean = re.sub(r"^\*\*[^*]+(?:\*\*:\s*|:\s*\*\*|\*\*)\s*", "", tok).strip()
            tok_clean = re.sub(r"^:\s*", "", tok_clean).strip()
            if tok_clean.startswith("<") and tok_clean.endswith(">"):
                tok_clean = tok_clean[1:-1].strip()
            # If it's an email
            if "@" in tok_clean and not tok_clean.startswith("[") and not tok_clean.startswith("http"):
                contact_entries.append(f"\\href{{mailto:{tok_clean}}}{{\\underline{{{tok_clean}}}}}")
            elif tok_clean.startswith("[") and "](" in tok_clean:
                m_link = re.match(r"^\[([^\]]+)\]\(([^)]+)\)$", tok_clean)
                if m_link:
                    lbl, u = m_link.group(1), m_link.group(2)
                    clean_lbl = lbl.replace("https://", "").replace("http://", "").rstrip("/")
                    clean_u = u.replace("%", "\\%")
                    contact_entries.append(f"\\href{{{clean_u}}}{{\\underline{{{escape_latex(clean_lbl)}}}}}")
                else:
                    contact_entries.append(format_inline_latex(tok_clean))
            elif tok_clean.startswith("http"):
                clean_u = tok_clean.replace("%", "\\%")
                display = tok_clean.replace("https://", "").replace("http://", "").rstrip("/")
                contact_entries.append(f"\\href{{{clean_u}}}{{\\underline{{{escape_latex(display)}}}}}")
            else:
                contact_entries.append(escape_latex(tok_clean))
        i += 1

    # Header LaTeX
    contact_line = " $|$ ".join(contact_entries)
    latex_parts = [
        r"\documentclass[letterpaper,10pt]{article}",
        r"",
        r"\usepackage{latexsym}",
        r"\usepackage[empty]{fullpage}",
        r"\usepackage{titlesec}",
        r"\usepackage{marvosym}",
        r"\usepackage[usenames,dvipsnames]{color}",
        r"\usepackage{verbatim}",
        r"\usepackage{enumitem}",
        r"\usepackage[hidelinks]{hyperref}",
        r"\usepackage{fancyhdr}",
        r"\usepackage[english]{babel}",
        r"\usepackage{tabularx}",
        r"\usepackage{needspace}",
        r"",
        r"\pagestyle{fancy}",
        r"\fancyhf{}",
        r"\renewcommand{\headrulewidth}{0pt}",
        r"\renewcommand{\footrulewidth}{0pt}",
        r"",
        r"% Adjust margins",
        r"\addtolength{\oddsidemargin}{-0.55in}",
        r"\addtolength{\evensidemargin}{-0.55in}",
        r"\addtolength{\textwidth}{1.1in}",
        r"\addtolength{\topmargin}{-.75in}",
        r"\addtolength{\textheight}{1.5in}",
        r"",
        r"\urlstyle{same}",
        r"\raggedbottom",
        r"\raggedright",
        r"\setlength{\tabcolsep}{0in}",
        r"",
        r"% Sections formatting",
        r"\titleformat{\section}{",
        r"  \vspace{-6pt}\scshape\raggedright\large",
        r"}{}{0em}{}[\color{black}\titlerule \vspace{-5pt}]",
        r"",
        r"% Custom commands",
        r"\newcommand{\resumeItem}[1]{",
        r"  \item\small{#1}\vspace{-3pt}",
        r"}",
        r"",
        r"\newcommand{\resumeSubheading}[4]{",
        r"  \needspace{4\baselineskip}\vspace{-2pt}\item",
        r"    \begin{tabular*}{0.97\textwidth}[t]{l@{\extracolsep{\fill}}r}",
        r"      \textbf{#1} & #2 \\",
        r"      \textit{\small#3} & \textit{\small #4} \\",
        r"    \end{tabular*}\vspace{-5pt}",
        r"}",
        r"",
        r"\newcommand{\resumeProjectHeading}[2]{",
        r"    \needspace{4\baselineskip}\vspace{-2pt}\item",
        r"    \begin{tabular*}{0.97\textwidth}[t]{p{0.86\textwidth}@{\extracolsep{\fill}}r}",
        r"      \raggedright\small#1 & #2 \\",
        r"    \end{tabular*}\vspace{-5pt}",
        r"}",
        r"",
        r"\newcommand{\resumeSubHeadingListStart}{\begin{itemize}[leftmargin=0.15in, label={}]}",
        r"\newcommand{\resumeSubHeadingListEnd}{\end{itemize}}",
        r"\newcommand{\resumeItemListStart}{\begin{itemize}[leftmargin=0.2in]}",
        r"\newcommand{\resumeItemListEnd}{\end{itemize}\vspace{-3pt}}",
        r"",
        r"\begin{document}",
        r"",
        r"\begin{center}",
        f"    \\textbf{{\\Huge \\scshape {escape_latex(candidate_name)}}} \\\\[2pt]",
        f"    \\small {contact_line}",
        r"\end{center}",
        r"",
    ]

    current_section = None
    in_subheading_list = False
    in_item_list = False

    def close_lists():
        nonlocal in_item_list, in_subheading_list
        res = []
        if in_item_list:
            res.append(r"\resumeItemListEnd")
            in_item_list = False
        if in_subheading_list:
            res.append(r"\resumeSubHeadingListEnd")
            in_subheading_list = False
        return res

    while i < total:
        line = lines[i]
        i += 1

        clean_l = _clean_glyphs(line).strip()
        if not line or clean_l in ["---", "--", "___", "- - -", "-"] or line.startswith("*Prepared for") or is_meta_commentary(clean_l):
            continue

        line = re.sub(r"\s+[-–—]{1,3}$", "", line).strip()

        # Section Header: ## Section Name
        if line.startswith("## "):
            latex_parts.extend(close_lists())
            raw_sec = re.sub(r"[*#_]+", "", line[3:]).strip()
            current_section = raw_sec.lower()
            latex_parts.append("")
            latex_parts.append(f"\\section{{{escape_latex(raw_sec)}}}")
            continue

        # Item Header: ### Title
        if line.startswith("### "):
            if in_item_list:
                latex_parts.append(r"\resumeItemListEnd")
                in_item_list = False

            if not in_subheading_list:
                latex_parts.append(r"\resumeSubHeadingListStart")
                in_subheading_list = True

            clean_item = line[4:].strip()
            # Check next lines for metadata (e.g. *Summer 2026*, *GitHub: ...*, *Core Technologies: ...*)
            meta_lines = []
            while i < total:
                next_l = lines[i].strip()
                if not next_l:
                    i += 1
                    continue
                # If next_l is a bullet point, STOP! It's not metadata.
                if re.match(r"^(?:[-+]|\d+[.)]|\*\s+)", next_l):
                    break
                if (next_l.startswith("*") and next_l.endswith("*")) or (next_l.startswith("_") and next_l.endswith("_")) or (not next_l.startswith(("#", "-", "*", "+")) and any(kw in next_l.lower() for kw in ["github:", "github.com/", "doi:", "doi.org/", "zenodo.org/", "core technologies:", "tech stack:", "technologies:"])):
                    meta_lines.append(next_l)
                    i += 1
                else:
                    break

            github_url = None
            doi_url = None
            tech_stack = None
            date_part = ""

            for ml in meta_lines:
                m_gh = re.search(r"https?://(?:www\.)?github\.com/[^\s)\]\"'>*]+", ml)
                if m_gh:
                    github_url = m_gh.group(0).rstrip("/*")
                m_doi = re.search(r"https?://(?:dx\.)?(?:doi\.org|zenodo\.org|arxiv\.org)/[^\s)\]\"'>*]+", ml)
                if m_doi:
                    doi_url = m_doi.group(0).rstrip("/*")
                if any(kw in ml.lower() for kw in ["core technologies:", "tech stack:", "technologies:"]):
                    tech_stack = re.sub(r"^\*?(?:core\s+technologies|tech\s+stack|technologies)[:\s]+", "", ml.strip("*").strip(), flags=re.I).strip()
                elif not date_part and not m_gh and not m_doi:
                    date_part = ml.strip("*").strip()

            is_publication = "publication" in (current_section or "")
            is_spices_paper = "scientific literature" in clean_item.lower() or "ieee spices" in clean_item.lower()

            if is_publication and is_spices_paper:
                if not doi_url:
                    doi_url = "https://doi.org/10.5281/zenodo.22676649"
                if not github_url:
                    github_url = "https://github.com/GenAI-Scientific-Literature-System/GenAI-Scientific-Literature-System-multi-agent-system"

            is_project = bool(github_url) or bool(doi_url) or ("project" in (current_section or "")) or is_publication

            if is_project:
                # Project or Publication Heading
                links = []
                if doi_url:
                    clean_doi = doi_url.replace("%", "\\%")
                    label = "Paper" if is_publication else "DOI"
                    links.append(f"\\href{{{clean_doi}}}{{\\underline{{{label}}}}}")
                if github_url:
                    clean_gh = github_url.replace("%", "\\%")
                    links.append(f"\\href{{{clean_gh}}}{{\\underline{{GitHub}}}}")

                if links:
                    date_or_link = " $|$ ".join(links)
                elif date_part:
                    date_or_link = escape_latex(date_part)
                else:
                    date_or_link = ""

                if "|" in clean_item:
                    parts = [p.strip() for p in clean_item.split("|", 1)]
                    title_text = parts[0]
                    stack_text = parts[1]
                else:
                    m_stack = re.match(r"^(.*?)\s*\(([^)]+)\)$", clean_item)
                    if m_stack:
                        title_text = m_stack.group(1).strip()
                        stack_text = m_stack.group(2).strip()
                    else:
                        title_text = clean_item
                        stack_text = tech_stack

                if is_publication and is_spices_paper and not stack_text:
                    stack_text = "IEEE SPICES"
                    title_text = re.sub(r"\s*\(?IEEE\s+SPICES\)?", "", title_text, flags=re.IGNORECASE).strip()

                if stack_text:
                    heading_content = f"\\textbf{{{format_inline_latex(title_text)}}} $|$ \\textit{{{format_inline_latex(stack_text)}}}"
                else:
                    heading_content = f"\\textbf{{{format_inline_latex(title_text)}}}"

                latex_parts.append(
                    f"    \\resumeProjectHeading\n"
                    f"      {{{heading_content}}}{{{date_or_link}}}"
                )
            elif "|" in clean_item:
                # Experience Subheading: Title | Company
                parts = [p.strip() for p in clean_item.split("|", 1)]
                title_part = parts[0]
                org_part = parts[1]
                
                latex_parts.append(
                    f"    \\resumeSubheading\n"
                    f"      {{{format_inline_latex(title_part)}}}{{{escape_latex(date_part)}}}\n"
                    f"      {{{format_inline_latex(org_part)}}}{{}}"
                )
            else:
                # Standard Subheading without '|'
                latex_parts.append(
                    f"    \\resumeSubheading\n"
                    f"      {{{format_inline_latex(clean_item)}}}{{{escape_latex(date_part)}}}\n"
                    f"      {{}}{{}}"
                )
            continue

        # Bullet point: - ... or * ...
        if re.match(r"^(?:[-*]|\d+[.)])\s+", line):
            bullet_text = re.sub(r"^(?:[-*]|\d+[.)])\s+", "", line).strip()
            
            # If we're inside education, skills, or certifications, bullets are standalone
            if "education" in (current_section or "") and not in_subheading_list:
                latex_parts.append(f"\\small{{{format_inline_latex(bullet_text)}}} \\\\[1pt]")
                continue
            elif "skills" in (current_section or "") and not in_subheading_list:
                latex_parts.append(f"\\small{{{format_inline_latex(bullet_text)}}} \\\\[2pt]")
                continue
            elif any(k in (current_section or "") for k in ["certifications", "courses", "licenses", "extracurricular"]) and not in_subheading_list:
                latex_parts.append(f"\\small{{\\textbf{{$\\bullet$}} {format_inline_latex(bullet_text)}}} \\\\[2pt]")
                continue

            # Standard Experience/Project bullet
            if not in_item_list:
                latex_parts.append(r"\resumeItemListStart")
                in_item_list = True

            latex_parts.append(f"    \\resumeItem{{{format_inline_latex(bullet_text)}}}")
            continue

        # Subheading or metadata without ### (e.g. *Sem 5* or *GitHub: ...*)
        if re.match(r"^\*[^*].*[^*]\*$", line):
            if not in_item_list:
                latex_parts.append(f"\\small{{\\textit{{{format_inline_latex(line[1:-1].strip())}}}}} \\\\[2pt]")
            continue

        # General body text (e.g. Career Objective, Education Institution header)
        if "career objective" in (current_section or ""):
            latex_parts.append(f"\\small{{{format_inline_latex(line)}}}\\\\[2pt]")
            continue

        if "education" in (current_section or ""):
            latex_parts.append(f"\\textbf{{{format_inline_latex(line)}}} \\\\[1pt]")
            continue

        latex_parts.append(f"\\small{{{format_inline_latex(line)}}} \\\\[2pt]")

    latex_parts.extend(close_lists())
    latex_parts.append(r"\end{document}")
    latex_parts.append("")

    return "\n".join(latex_parts)


def compile_latex_to_pdf(tex_content: str, output_pdf_path: str, tex_filepath: Optional[str] = None) -> bool:
    """Compile LaTeX content into a PDF using Tectonic.
    
    Returns True if compilation succeeded, False otherwise.
    """
    output_pdf_path = os.path.abspath(output_pdf_path)
    output_dir = os.path.dirname(output_pdf_path)
    os.makedirs(output_dir, exist_ok=True)

    if not tex_filepath:
        tex_filepath = output_pdf_path.replace(".pdf", ".tex")
    else:
        tex_filepath = os.path.abspath(tex_filepath)

    with open(tex_filepath, "w", encoding="utf-8") as f:
        f.write(tex_content)

    tectonic_bin = shutil.which("tectonic") or "/opt/homebrew/bin/tectonic"
    if not os.path.exists(tectonic_bin):
        print(f"Warning: Tectonic binary not found at '{tectonic_bin}'.", flush=True)
        return False

    try:
        res = subprocess.run(
            [tectonic_bin, "-o", output_dir, tex_filepath],
            capture_output=True,
            text=True,
            timeout=45,
        )
        if res.returncode == 0 and os.path.exists(output_pdf_path):
            return True
        else:
            print(f"Tectonic compilation failed (code {res.returncode}):\n{res.stderr}", flush=True)
            return False
    except Exception as e:
        print(f"Error running Tectonic: {e}", flush=True)
        return False
