import os
import re
import sys
from groq import Groq
import db
import config
from pdf_utils import markdown_to_pdf
import github_portfolio
import profiles


# Live-probe verified working OpenRouter free-tier models (sorted by latency, probe 2026-09-29)
PREFERRED_OPENROUTER_MODELS = (
    "nvidia/nemotron-3-super-120b-a12b:free",  # 0.992s — 120B MoE, best free frontier
    "google/gemma-4-31b-it:free",              # 1.2s  — Google 31B, solid fallback
    "google/gemma-4-26b-a4b-it:free",          # 1.3s  — Google 26B MoE
    "nvidia/nemotron-3.5-content-safety:free", # verified working
    "nvidia/nemotron-3-ultra-550b-a55b:free",  # large frontier, slower
)




def strip_certifications(markdown: str) -> str:
    """Strip Certifications section and unshared course credentials from resume markdown."""
    if not markdown:
        return ""

    lines = markdown.splitlines()
    output = []
    in_certifications = False

    for line in lines:
        cleaned = re.sub(r"[*_`]", "", line).strip().lower()
        if re.match(r"^#{1,3}\s+(certifications?|courses?\s+(?:&|and)\s+certifications?|certifications?\s+(?:&|and)\s+licenses?|licenses?\s+(?:&|and)\s+certifications?)\s*$", cleaned):
            in_certifications = True
            # Strip trailing horizontal rule before certifications if present
            while output and (output[-1].strip() == "---" or not output[-1].strip()):
                output.pop()
            continue

        if in_certifications:
            # End of certifications when another major section or footer begins
            if re.match(r"^#{1,3}\s+", line) or line.strip().startswith("*Prepared for"):
                in_certifications = False
                output.append("")
                output.append("---")
                output.append("")
                output.append(line)
            continue

        output.append(line)

    result = "\n".join(output)
    result = re.sub(r"\n(?:---\s*\n)+---\s*\n", "\n---\n", result)
    return result.strip() + "\n"


def scrub_unverified_metrics(markdown: str, profile_id: str = "") -> str:
    """Scrub known hallucinated metrics from candidate resume."""
    if not markdown:
        return ""

    if profile_id in ("secondary", "mahika", "partner"):
        # Strip hallucinated test coverage percentages (e.g. >90%, >95%)
        markdown = re.sub(
            r"(?:covering\s+)?(?:>|≥|approximately|~)?\s*\d{2,3}\s*%\s*(?:of\s+service\s+layer\s+methods|test\s+coverage)",
            "comprehensive unit and integration test coverage",
            markdown,
            flags=re.IGNORECASE
        )
        # Strip hallucinated TA proficiency percentages and student counts
        markdown = re.sub(
            r"(?:improving|improved|enhancing|strengthening)\s+(?:student\s+)?(?:coding\s+proficiency|code\s+quality)?\s*(?:by\s+)?(?:≈|~|approximately)?\s*\d{1,2}\s*%\s*(?:\([^)]*assessment\s+scores[^)]*\)|across\s+(?:≈|~|approximately)?\s*\d+\s+students)?",
            "strengthening students' foundational programming concepts",
            markdown,
            flags=re.IGNORECASE
        )
        markdown = re.sub(
            r"(?:by\s+)?(?:≈|~|approximately)?\s*\d{1,2}\s*%\s*\([^)]*assessment\s+scores[^)]*\)",
            "strengthening foundational programming concepts",
            markdown,
            flags=re.IGNORECASE
        )
        markdown = re.sub(
            r"across\s+(?:≈|~|approximately)?\s*\d+\s+students",
            "for first-year B.Tech students",
            markdown,
            flags=re.IGNORECASE
        )
        # Strip hallucinated TAMS registration percentages
        markdown = re.sub(
            r"(?:increasing|increased|boosting)\s+participant\s+registrations\s+(?:by\s+)?(?:≈|~|approximately)?\s*\d{1,2}\s*%\s*(?:through\s+targeted\s+campaigns)?",
            "driving participant outreach and technical event engagement",
            markdown,
            flags=re.IGNORECASE
        )
        markdown = re.sub(
            r"increasing\s+participant\s+registrations\s+by\s+(?:≈|~|approximately)?\s*\d{1,2}\s*%\s*(?:through\s+targeted\s+campaigns)?",
            "driving participant outreach and technical event engagement",
            markdown,
            flags=re.IGNORECASE
        )
        # Strip hallucinated TPS (e.g. 200 TPS)
        markdown = re.sub(
            r"\s*\((?:simulated\s+)?\d+\s*TPS\)",
            "",
            markdown,
            flags=re.IGNORECASE
        )
        # Strip hallucinated AUC in Matcher
        markdown = re.sub(
            r"\s*\((?:AUC|ROC-AUC)\s*=\s*0\.\d+\)",
            "",
            markdown,
            flags=re.IGNORECASE
        )
        # Strip hallucinated vulnerability counts (e.g. 12 critical vulnerabilities)
        markdown = re.sub(
            r"identifying\s+and\s+remediating\s+\d+\s+critical\s+vulnerabilities",
            "identifying and remediating application security vulnerabilities",
            markdown,
            flags=re.IGNORECASE
        )

    # 1. Strip 'robotics' and fabricated non-CS hardware/FPGA terms from Career Objective
    def _clean_obj(m):
        block = m.group(0)
        cleaned = re.sub(r",?\s*(?:embedded\s+)?robotics\s*,?", ", ", block, flags=re.IGNORECASE)
        cleaned = re.sub(r"\band\s+robotics\b", "and full-stack development", cleaned, flags=re.IGNORECASE)
        # Scrub fabricated non-CS electronics, analog, and FPGA claims
        cleaned = re.sub(r"\b(?:solid\s+grounding\s+in\s+)?electronic\s+circuits\b", "strong grounding in low-level C programming", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(?:digital/analogue|analogue/digital|digital/analog|analog/digital)\s+(?:circuit\s+)?design\b", "operating-system internals", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bhigh-speed\s+board\s+(?:and\s+FPGA\s+development|design)\b", "high-performance telecom networking platforms", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bhardware\s+engineering\s+internship\b", "embedded software engineering internship", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\btelecom-grade\s+hardware\s+R&D\b", "telecom-grade embedded software R&D", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(?:contribute\s+to\s+)?high-performance\s+hardware\s+and\s+FPGA\s+design\b", "contribute to high-performance networking platforms and embedded system software", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r",?\s*and\s+FPGA(?:\s+design|\s+development)?\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bFPGA(?:\s+design|\s+development)?\b", "embedded software", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r",\s*,", ", ", cleaned)
        cleaned = re.sub(r",\s*and\b", " and", cleaned)
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        return cleaned

    markdown = re.sub(r"##\s*Career Objective.*?(?=\n##|\Z)", _clean_obj, markdown, flags=re.DOTALL | re.IGNORECASE)

    # 1.5. Clean fabricated non-CS hardware/FPGA terms from Technical Skills
    def _clean_skills(m):
        skills_block = m.group(0)
        cleaned = re.sub(r",?\s*VHDL/Verilog\s*(?:\([^)]*\))?", "", skills_block, flags=re.IGNORECASE)
        cleaned = re.sub(r",?\s*(?:digital/analogue|analogue/digital|digital/analog|analog/digital)\s+circuit\s+fundamentals", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r",?\s*electronic\s+circuits", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r",?\s*(?:high-speed\s+board\s+design|FPGA(?:\s+design|\s+development)?)", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bEmbedded\s*/\s*Hardware:", "Embedded & Systems Software:", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r",\s*,", ", ", cleaned)
        cleaned = re.sub(r",\s*$", "", cleaned, flags=re.MULTILINE)
        return cleaned

    markdown = re.sub(r"##\s*Technical Skills.*?(?=\n##|\Z)", _clean_skills, markdown, flags=re.DOTALL | re.IGNORECASE)

    # 2. Enforce explicit long forms ONLY for the requested terms
    markdown = re.sub(r"\bDBMS\b", "Database management systems", markdown)
    markdown = re.sub(r"\bB\.?\s*Tech\b", "Bachelor of Technology", markdown)

    # Revert accidental mangling of paper titles or phrases
    markdown = re.sub(r"\bMulti-Agent\s+Generative\s+AI\s+and\s+applications\s+System\b", "A Multi-Agent Generative AI System", markdown, flags=re.IGNORECASE)
    markdown = re.sub(r"\bGenerative\s+AI\s+and\s+applications\s+System\b", "Generative AI System", markdown, flags=re.IGNORECASE)
    markdown = re.sub(r"\bIntegrated\s+Generative\s+AI\s+and\s+applications\b", "Integrated Generative AI", markdown, flags=re.IGNORECASE)
    markdown = re.sub(r"\bGenerative\s+AI\s+and\s+applications\s+solutions\b", "Generative AI solutions", markdown, flags=re.IGNORECASE)
    markdown = re.sub(r"\bGenerative\s+AI\s+and\s+applications\s+candidate\b", "Generative AI candidate", markdown, flags=re.IGNORECASE)

    if profile_id in ("secondary", "mahika", "partner"):
        # Expand course name "Generative AI" to "Generative AI and applications" strictly within Relevant Coursework
        def _expand_coursework(m):
            return re.sub(r"\bGenerative\s+AI\b(?!\s+and\s+applications)", "Generative AI and applications", m.group(0), flags=re.IGNORECASE)
        markdown = re.sub(r"(?:Relevant\s+Coursework|Coursework)[:\s][^\n]+", _expand_coursework, markdown, flags=re.IGNORECASE)

    # Normalize percent spacing: "92.7 %" -> "92.7%"
    markdown = re.sub(r"(\d+(?:\.\d+)?)\s+%", r"\1%", markdown)

    # 3. Clean all UTF-8 Mojibake and enforce standard ASCII
    markdown = markdown.replace("‚Äî", "-").replace("‚Üí", "->").replace("‚â•", ">=")
    markdown = markdown.replace("â€\"", "-").replace("â†'", "->").replace("â‰¥", ">=")
    markdown = markdown.replace("â€“", "-").replace("â€™", "'").replace("â€œ", '"').replace("â€\x9d", '"')
    markdown = markdown.replace("--", "-").replace("-", "-").replace("‑", "-")
    markdown = markdown.replace("→", "->").replace("←", "<-").replace("≥", ">=").replace("≤", "<=")
    markdown = markdown.replace("\u202f", " ").replace("\u00a0", " ")

    # 4. Remove banned projects if present
    markdown = re.sub(r"###\s*.*?(?:PC\s+Parts|University\s+Database).*?(?=\n###|\n##|\Z)", "", markdown, flags=re.DOTALL | re.IGNORECASE)

    # 4.5. Remove duplicate scientific literature projects if GLAS-Med is already present in Selected Projects
    if "glas-med" in markdown.lower() or "clinical literature synthesis" in markdown.lower():
        def _dedup_projects(m):
            sec_text = m.group(0)
            cleaned_sec = re.sub(
                r"###\s*[^\n]*(?:scientific\s+literature\s+analysis|genai-scientific-literature).*?(?=(?:\n###|\Z))",
                "",
                sec_text,
                flags=re.DOTALL | re.IGNORECASE
            )
            return cleaned_sec

        markdown = re.sub(r"##\s*(?:Selected\s+Projects|Academic\s+Projects|Projects)\b.*?(?=\n##\s+[^\n#]|\Z)", _dedup_projects, markdown, flags=re.DOTALL | re.IGNORECASE)

    # 5. Normalize bold job titles to ### headings if LLM output **Role - Company** (Dates)
    markdown = re.sub(
        r"^\*\*(Software Engineering Intern\s*[--]\s*[^*]+)\*\*\s*(?:\(([^)]+)\))?",
        r"### \1\n*\2*",
        markdown,
        flags=re.MULTILINE
    )

    return markdown


def enforce_one_page_budget(markdown: str, profile_id: str = "madhav", strict_mode: bool = False) -> str:
    """Deterministically enforce 1-page bullet and project limits for 1-page curated profiles."""
    if not markdown:
        return markdown

    lines = markdown.splitlines()
    output = []
    current_sec = None
    current_item = None
    item_bullets = 0
    projects_count = 0

    max_qualcomm = 3
    max_octanner = 1 if strict_mode else 2
    max_pub = 2 if strict_mode else 3
    max_drdo = 2 if strict_mode else 3
    max_leadership = 2
    max_proj_count = 2 if strict_mode else 3
    max_proj_bullets = 2

    # Track seen roles to avoid duplicate listings across sections
    seen_roles = set()

    i = 0
    while i < len(lines):
        line = lines[i]

        # Section header
        if re.match(r"^##\s+", line):
            current_sec = re.sub(r"[*_#]", "", line).strip().lower()
            current_item = None
            item_bullets = 0
            output.append(line)
            i += 1
            continue

        # Item header: ### Title
        if re.match(r"^###\s+", line):
            current_item = line.strip().lower()
            item_bullets = 0

            # Deduplication: If teaching assistant or tams was already added, skip duplicate
            if "teaching assistant" in current_item:
                if "ta" in seen_roles:
                    i += 1
                    while i < len(lines) and not re.match(r"^###?\s+", lines[i]) and lines[i] != "---":
                        i += 1
                    continue
                seen_roles.add("ta")
            elif "social media" in current_item or "tams" in current_item:
                if "tams" in seen_roles:
                    i += 1
                    while i < len(lines) and not re.match(r"^###?\s+", lines[i]) and lines[i] != "---":
                        i += 1
                    continue
                seen_roles.add("tams")

            if any(k in (current_sec or "") for k in ["project", "academic", "selected"]):
                projects_count += 1
                if projects_count > max_proj_count:
                    # Skip projects beyond the budget
                    i += 1
                    while i < len(lines) and not re.match(r"^##\s+", lines[i]):
                        i += 1
                    continue
            output.append(line)
            i += 1
            continue

        # Bullet point
        if re.match(r"^(?:[-*]|\d+[.)])\s+", line):
            if "qualcomm" in (current_item or ""):
                if item_bullets >= max_qualcomm:
                    i += 1
                    continue
            elif "tanner" in (current_item or ""):
                if item_bullets >= max_octanner:
                    i += 1
                    continue
            elif "drdo" in (current_item or "") or "radar" in (current_item or ""):
                if item_bullets >= max_drdo:
                    i += 1
                    continue
            elif "teaching assistant" in (current_item or ""):
                if item_bullets >= 1:
                    i += 1
                    continue
            elif "social media" in (current_item or ""):
                if item_bullets >= 1:
                    i += 1
                    continue
            elif "publication" in (current_sec or ""):
                if item_bullets >= max_pub:
                    i += 1
                    continue
            elif "extracurricular" in (current_sec or ""):
                if item_bullets >= 1:
                    i += 1
                    continue
            elif any(k in (current_sec or "") for k in ["leadership"]):
                if item_bullets >= max_leadership:
                    i += 1
                    continue
            elif any(k in (current_sec or "") for k in ["project", "academic", "selected"]):
                if item_bullets >= max_proj_bullets:
                    i += 1
                    continue

            item_bullets += 1
            output.append(line)
            i += 1
            continue

        output.append(line)
        i += 1

    return "\n".join(output) + ("\n" if markdown.endswith("\n") else "")


def strip_meta_commentary(markdown: str) -> str:
    """Remove any LLM meta-commentary, footer disclaimers, or compilation notes."""
    if not markdown:
        return markdown
    output = []
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
    for line in markdown.splitlines():
        cleaned = re.sub(r"^[*_`#\s]+|[*_`#\s]+$", "", line).strip().lower()
        if any(re.search(pat, cleaned) for pat in meta_patterns):
            continue
        output.append(line)
    return "\n".join(output) + ("\n" if markdown.endswith("\n") else "")


def strip_robotic_bullet_labels(markdown: str) -> str:
    """Strip repetitive meta-labels like '**What it does**:' or '**Architecture & Impact**:' from bullet items."""
    if not markdown:
        return markdown
    output = []
    robotic_pattern = re.compile(
        r"^(\s*[-*+]\s+)\*\*(?:What it does|Architecture & Impact|Architecture|Overview|Impact|Core Functionality|Technical Architecture|Role & Impact)\*\*:\s*",
        re.IGNORECASE,
    )
    for line in markdown.splitlines():
        if robotic_pattern.match(line):
            line = robotic_pattern.sub(r"\1", line)
            m = re.match(r"^(\s*[-*+]\s+)([a-z])(.*)", line)
            if m:
                line = f"{m.group(1)}{m.group(2).upper()}{m.group(3)}"
        output.append(line)
    return "\n".join(output) + ("\n" if markdown.endswith("\n") else "")


def ensure_education(markdown: str, profile=None) -> str:
    """Ensure candidate's Education section is present in the tailored resume."""
    if not markdown:
        return markdown

    for line in markdown.splitlines():
        cleaned = re.sub(r"[*_`#]", "", line).strip().lower()
        if cleaned == "education":
            return markdown

    if profile and getattr(profile, "id", "") in ("secondary", "mahika", "partner"):
        edu_block = (
            "## Education\n\n"
            "**PES University, Bengaluru**\n"
            "- Bachelor of Technology in Computer Science and Engineering\n"
            "- Expected Graduation: **May 2027**\n"
            "- **CGPA**: **8.06 (Sem 6)** | **Distinction Scholarship** (Semesters 1, 3, 4, 5, 6)\n"
            "- **Relevant Coursework**: Data Structures and Applications, Design and Analysis of Algorithms, Operating Systems, Computer Networks, Database Management Systems, Machine Learning, Generative AI and Applications\n"
        )
    else:
        edu_block = (
            "## Education\n\n"
            "**PES University, Bengaluru**\n"
            "- Bachelor of Technology in Computer Science and Engineering\n"
            "- Expected Graduation: **May 2027**\n"
            "- **Relevant Coursework**: Data Structures & Algorithms, Operating Systems, Computer Networks, Database Management Systems, Machine Learning, Linear Algebra\n"
        )

    lines = markdown.splitlines()
    output = []
    inserted = False

    for line in lines:
        cleaned = re.sub(r"[*_`#]", "", line).strip().lower()
        if not inserted and cleaned.startswith("professional experience"):
            output.append(edu_block.strip())
            output.append("")
            output.append("---")
            output.append("")
            inserted = True
        output.append(line)

    if not inserted:
        output = []
        in_obj = False
        for line in lines:
            output.append(line)
            cleaned = re.sub(r"[*_`#]", "", line).strip().lower()
            if cleaned.startswith("career objective"):
                in_obj = True
            elif in_obj and line.strip() in ["---", "--", "___"]:
                output.append("")
                output.append(edu_block.strip())
                output.append("")
                output.append("---")
                in_obj = False
                inserted = True

    if not inserted:
        return edu_block + "\n\n---\n\n" + markdown

    return "\n".join(output) + ("\n" if markdown.endswith("\n") else "")


def ensure_gpa(markdown: str, profile=None) -> str:
    """Ensure candidate's GPA is present under Education if required by profile."""
    if not markdown or not profile or not getattr(profile, "include_gpa", False):
        return markdown

    gpa_text = getattr(profile, "gpa_text", None)
    if not gpa_text:
        return markdown

    if "8.06" in markdown or "distinction scholarship" in markdown.lower():
        return markdown

    lines = markdown.splitlines()
    output = []
    in_education = False
    gpa_inserted = False

    for line in lines:
        cleaned = re.sub(r"[*_`]", "", line).strip().lower()
        if re.match(r"^#{1,3}\s+education\s*$", cleaned):
            in_education = True

        output.append(line)

        if in_education and not gpa_inserted:
            if "pes university" in line.lower():
                output.append(f"- **CGPA**: **8.06 (Sem 6)** | **Distinction Scholarship** (Semesters 1, 3, 4, 5, 6)")
                gpa_inserted = True

        if in_education and re.match(r"^#{1,3}\s+", line) and not re.match(r"^#{1,3}\s+education\s*$", cleaned):
            in_education = False

    return "\n".join(output) + ("\n" if markdown.endswith("\n") else "")


def ensure_publication_links(markdown: str) -> str:
    """Ensure the IEEE SPICES publication has both the verified Paper URL (Zenodo DOI) and GitHub repository directly on the header line."""
    if not markdown:
        return markdown
    paper_url = "https://doi.org/10.5281/zenodo.22676649"
    github_url = "https://github.com/GenAI-Scientific-Literature-System/GenAI-Scientific-Literature-System-multi-agent-system"
    if "scientific literature" in markdown.lower() or "ieee spices" in markdown.lower():
        # Strip any stray Paper / GitHub metadata lines anywhere in the publication section
        lines = []
        in_pub = False
        for l in markdown.split("\n"):
            clean_l = l.strip().lower()
            if clean_l.startswith("## ") and "publication" in clean_l:
                in_pub = True
            elif in_pub and clean_l.startswith("## "):
                in_pub = False
            
            # If inside publications and line is just a metadata link line, remove it
            if in_pub and (
                any(clean_l.startswith(p) for p in ["*paper:", "*github:", "_paper:", "_github:", "paper:", "github:"])
                or ("doi.org" in clean_l and "github.com" in clean_l)
            ):
                continue
            
            # Strip redundant raw DOI / GitHub URLs from bullet points
            if in_pub and l.strip().startswith(("-", "* ")) and any(k in clean_l for k in ["doi:", "github:", "zenodo.org", "doi.org"]):
                l = re.sub(r";?\s*(?:DOI|Paper|Repository):\s*\[?[^\s|\]]+\]?(?:\([^\)]+\))?\s*\|\s*GitHub:\s*\[?[^\s\n\]]+\]?(?:\([^\)]+\))?", "", l, flags=re.I).rstrip("; ")
            
            lines.append(l)
        
        cleaned_md = "\n".join(lines)
        
        # Standardize the publication heading to canonical ### format with metadata immediately below
        canonical_heading = "### A Multi-Agent Generative AI System for Scientific Literature Analysis | IEEE SPICES"
        canonical_meta = f"*Paper: {paper_url} | GitHub: {github_url}*"
        replacement_block = f"{canonical_heading}\n{canonical_meta}\n"
        
        # Replace existing heading line (matching ###, **, or plain line)
        replaced = False
        def _rep_heading(m):
            nonlocal replaced
            replaced = True
            return replacement_block
        
        cleaned_md = re.sub(
            r"^(?:###|\*\*)[^\n]*(?:scientific\s+literature|ieee\s+spices)[^\n]*$",
            _rep_heading,
            cleaned_md,
            count=1,
            flags=re.IGNORECASE | re.MULTILINE
        )
        if not replaced:
            cleaned_md = re.sub(
                r"^[^\n#*]*(?:scientific\s+literature|ieee\s+spices)[^\n]*$",
                _rep_heading,
                cleaned_md,
                count=1,
                flags=re.IGNORECASE | re.MULTILINE
            )
        
        return cleaned_md
    return markdown


def ensure_selected_project_github_links(markdown: str, portfolio: list[dict], profile=None) -> str:
    """Ensure selected projects have strictly verified GitHub repository links.

    1. If a project has a verified repository URL:
       - Ensures the exact verified repository URL is placed beneath the project heading.
       - Replaces any wrong, hallucinated, or placeholder URLs (such as /Portfolio).
    2. If a project does NOT have a verified repository URL:
       - Removes any hallucinated or placeholder GitHub lines under that project.
    """
    if not markdown:
        return ""

    def normalize(value: str) -> str:
        value = re.sub(r"\[[^]]+\]\([^)]*\)", "", value)
        value = re.sub(r"\([^)]*\)", "", value)
        return re.sub(r"[^a-z0-9]+", "", value.lower())

    projects = []
    if portfolio:
        for project in portfolio:
            url = (project.get("url") or "").strip()
            if not url or "github.com/" not in url.lower():
                continue
            if "/portfolio" in url.lower():
                continue
            names = [project.get("name", ""), project.get("display_name", ""), project.get("full_name", "")]
            names = [normalize(name) for name in names if name]
            if names:
                projects.append((names, url))

    KNOWN_PROJECT_URLS = {
        "neuro": "https://github.com/madhavofficial/neuro_capstone",
        "symbolic": "https://github.com/madhavofficial/neuro_capstone",
        "pathogenicity": "https://github.com/madhavofficial/neuro_capstone",
        "sketch": "https://github.com/madhavofficial/Drawing-A-New-Way-To-Search-ML-",
        "drawing": "https://github.com/madhavofficial/Drawing-A-New-Way-To-Search-ML-",
        "careertime": "https://github.com/madhavofficial/CareerTime",
        "career": "https://github.com/madhavofficial/CareerTime",
        "glas": "https://github.com/madhavofficial/evidence-grounded-clinical-literature-synthesis",
        "clinical": "https://github.com/madhavofficial/evidence-grounded-clinical-literature-synthesis",
        "kafka": "https://github.com/varunnhn/153_Project3_BD",
        "stream": "https://github.com/varunnhn/153_Project3_BD",
        "153_project3_bd": "https://github.com/varunnhn/153_Project3_BD",
        "bike": "https://github.com/madhavofficial/Forecasting-Bike-Rental-Demand",
        "rental": "https://github.com/madhavofficial/Forecasting-Bike-Rental-Demand",
        "trader": "https://github.com/madhavofficial/Ultimate-Trader-Dashboard-GitHub-Repository-Structure",
        "trading": "https://github.com/madhavofficial/Ultimate-Trader-Dashboard-GitHub-Repository-Structure",
        "watchlist": "https://github.com/madhavofficial/Ultimate-Trader-Dashboard-GitHub-Repository-Structure",
        "hunter": "https://github.com/madhavofficial/job-hunter",
        "caregiver": "https://github.com/madhavofficial/Caregiver-Coordination-Hub",
        "arena": "https://github.com/madhavofficial/oa-arena-windows",
        "unionfs": "https://github.com/madhavofficial/mini-unionfs",
        "mini-unionfs": "https://github.com/madhavofficial/mini-unionfs",
        "mini_unionfs": "https://github.com/madhavofficial/mini-unionfs",
        "fuse": "https://github.com/madhavofficial/mini-unionfs",
    }

    known_urls = getattr(profile, "known_project_urls", None)
    if known_urls is None and isinstance(profile, dict):
        known_urls = profile.get("known_project_urls")
    if known_urls is None:
        known_urls = KNOWN_PROJECT_URLS

    def is_github_line(text: str) -> bool:
        t = text.strip()
        if re.search(r"^\s*\*?\[?(?:github|repo|repository)\]?[:\s]+<?(https?://[^\s>]+)>?\*?\s*$", t, re.I):
            return True
        if "github.com/" in t.lower() and (t.startswith("*") or t.startswith("[") or t.startswith("- [GitHub]")):
            return True
        if re.match(r"^\s*\*?(?:no\s+public\s+(?:repository|repo)|private\s+repo(?:sitory)?)\*?\s*$", t, re.I):
            return True
        return False

    lines = markdown.splitlines()
    output = []
    in_selected_projects = False
    current_matched_url = None
    url_handled_for_project = False

    i = 0
    while i < len(lines):
        line = lines[i]
        heading_match = re.match(r"^##\s+(.+?)\s*$", line)
        if heading_match:
            norm_heading = normalize(heading_match.group(1))
            in_selected_projects = any(kw in norm_heading for kw in ["selectedprojects", "academicengineeringprojects", "projects"])
            current_matched_url = None
            url_handled_for_project = False
            output.append(line)
            i += 1
            continue

        if in_selected_projects and re.match(r"^###\s+", line):
            heading_name = normalize(re.sub(r"^###\s+", "", line))
            matched_url = None
            matched_length = 0

            # 1. Match against portfolio
            for names, url in projects:
                for name in names:
                    if name and (name in heading_name or heading_name in name) and len(name) > matched_length:
                        matched_url = url
                        matched_length = len(name)

            # 2. Match against profile known_urls
            if not matched_url:
                tokens = re.findall(r"[a-z0-9]{3,}", re.sub(r"\([^)]*\)", "", line).lower())
                for t in tokens:
                    if t in known_urls:
                        matched_url = known_urls[t]
                        break

            if matched_url and "/portfolio" in matched_url.lower():
                matched_url = None

            current_matched_url = matched_url
            output.append(line)

            # Look ahead for an existing link line
            next_idx = i + 1
            has_existing_link = False
            while next_idx < len(lines) and not lines[next_idx].strip():
                next_idx += 1

            if next_idx < len(lines) and is_github_line(lines[next_idx]):
                has_existing_link = True

            if matched_url:
                output.append(f"*GitHub: {matched_url}*")
                url_handled_for_project = True
                if has_existing_link:
                    i = next_idx + 1
                    continue
            else:
                url_handled_for_project = True
                if has_existing_link:
                    i = next_idx + 1
                    continue

            i += 1
            continue

        if in_selected_projects and is_github_line(line):
            if current_matched_url and not url_handled_for_project:
                output.append(f"*GitHub: {current_matched_url}*")
                url_handled_for_project = True
            # Drop unverified or duplicate link lines
            i += 1
            continue

        output.append(line)
        i += 1

    return "\n".join(output) + ("\n" if markdown.endswith("\n") else "")


def ensure_career_objective_target(markdown: str, company: str = "", title: str = "") -> str:
    """Ensure Career Objective is professional, employment-ready, and free of company/role references."""
    if not markdown:
        markdown = ""

    lines = markdown.splitlines()
    objective_index = None
    for index, line in enumerate(lines):
        heading_text = re.sub(r"[*_`]", "", line.strip())
        clean_title = re.sub(r"^#{1,3}\s+", "", heading_text).strip().lower()
        if clean_title == "career objective":
            objective_index = index
            break
        elif clean_title.startswith("career objective"):
            objective_index = index
            lines[index] = "## Career Objective"
            remainder = re.sub(r"^#{1,3}\s+[*_]*career objective[*_]*[\s:–—\-]*", "", line.strip(), flags=re.IGNORECASE).strip()
            if remainder:
                lines.insert(index + 1, remainder)
            break

    is_mahika = "mahika" in markdown.lower()
    if is_mahika:
        default_objective = (
            "Employment-ready Computer Science engineer specializing in machine learning, full-stack systems, "
            "and data pipelines. Seeking engineering roles to build resilient, production-grade software and high-impact solutions."
        )
        seeking_suffix = "Seeking engineering roles to build resilient, production-grade software and high-impact solutions."
    else:
        default_objective = (
            "Employment-ready Computer Science engineer specializing in backend systems and autonomous AI workflows. "
            "Seeking Software Engineering roles to build resilient, production-grade software and distributed solutions."
        )
        seeking_suffix = "Seeking Software Engineering roles to build resilient, production-grade software and distributed solutions."

    if objective_index is None:
        insert_at = 1 if lines and re.match(r"^#\s+", lines[0]) else 0
        lines[insert_at:insert_at] = ["## Career Objective", default_objective, ""]
        return "\n".join(lines) + ("\n" if markdown.endswith("\n") else "")

    next_heading = len(lines)
    for index in range(objective_index + 1, len(lines)):
        if re.match(r"^#{1,3}\s+", lines[index]):
            next_heading = index
            break

    company_clean = (" ".join((company or "").split())).strip()
    title_clean = (" ".join((title or "").split())).strip()

    valid_sentences = []
    for idx in range(objective_index + 1, next_heading):
        line = lines[idx].strip()
        if not line:
            continue
        # Split line into individual sentences to cleanly drop targeting clauses without losing base attributes
        raw_sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", line) if s.strip()]
        for sent in raw_sentences:
            # Drop targeting clauses
            if re.search(r"\btargeting\b", sent, re.I):
                continue
            if re.search(r"\bposition\s+at\b|\brole\s+at\b|\binternship\s+at\b", sent, re.I):
                continue
            # Drop company name references
            if company_clean and re.search(r"\b" + re.escape(company_clean) + r"\b", sent, re.I):
                continue
            # Scrub specific title references in targeting context
            if title_clean and re.search(r"\b" + re.escape(title_clean) + r"\b", sent, re.I):
                sent = re.sub(r"\*+" + re.escape(title_clean) + r"\*+", "Software Engineering", sent, flags=re.I)
                sent = re.sub(re.escape(title_clean), "Software Engineering", sent, flags=re.I)
            sent = " ".join(sent.split()).strip()
            if sent:
                valid_sentences.append(sent)

    if not valid_sentences:
        valid_sentences = [default_objective]
    else:
        full_text = " ".join(valid_sentences)
        if "employment-ready" not in full_text.lower() and "employment ready" not in full_text.lower():
            orig = valid_sentences[0]
            if re.search(r"\b(aspiring|motivated|passionate)\s+computer\s+science\s+(?:student|undergraduate|engineer)\b", orig, flags=re.I):
                valid_sentences[0] = re.sub(
                    r"\b(aspiring|motivated|passionate)\s+computer\s+science\s+(?:student|undergraduate|engineer)\b",
                    "Employment-ready Computer Science engineer",
                    orig,
                    count=1,
                    flags=re.I,
                )
            elif re.search(r"\bcomputer\s+science\s+(?:student|undergraduate)\b", orig, flags=re.I):
                valid_sentences[0] = re.sub(
                    r"\bcomputer\s+science\s+(?:student|undergraduate)\b",
                    "Employment-ready Computer Science engineer",
                    orig,
                    count=1,
                    flags=re.I,
                )
            elif re.search(r"\bsoftware\s+engineering\s+(?:student|undergraduate)\b", orig, flags=re.I):
                valid_sentences[0] = re.sub(
                    r"\bsoftware\s+engineering\s+(?:student|undergraduate)\b",
                    "Employment-ready software engineer",
                    orig,
                    count=1,
                    flags=re.I,
                )
            else:
                valid_sentences[0] = f"Employment-ready Computer Science engineer. {orig}"

        # If only 1 sentence remains without a seeking clause, ensure the punchy second sentence is included
        if len(valid_sentences) == 1 and not re.search(r"\bseeking\b", valid_sentences[0], re.I):
            valid_sentences.append(seeking_suffix)

    # Normalize punctuation and sentences
    final_body = []
    for s in valid_sentences:
        s = re.sub(r"\s+([.,;:!?])", r"\1", s)
        s = re.sub(r"\.{2,}", ".", s)
        s = re.sub(r"\s{2,}", " ", s).strip()
        if s and not s.endswith(('.', '!', '?')):
            s += "."
        if s:
            final_body.append(s)

    combined_body = " ".join(final_body)
    new_lines = lines[:objective_index + 1] + [combined_body, ""] + lines[next_heading:]
    return "\n".join(new_lines) + ("\n" if markdown.endswith("\n") else "")


def is_job_description_ambiguous(title: str, description: str) -> tuple[bool, str]:
    """Detects if a job description is ambiguous, multi-track, general development centre,
    or early-career talent pool requiring a broad portfolio presentation.
    """
    t = (title or "").lower()
    d = (description or "").lower()

    # 1. Explicit multi-role, talent pool, or general listing markers
    pooling_markers = [
        "multiple potential roles", "outlines multiple", "multiple roles across",
        "various roles across", "various roles", "considered as openings arise", "general listing",
        "talent pool", "talent pooling", "rotational", "development centre", "development center",
        "idc", "various teams", "multiple teams", "future openings", "early career program",
        "campus hiring", "graduate trainee", "general software engineer", "rotational program",
        "explore different areas", "multiple engineering disciplines"
    ]
    for marker in pooling_markers:
        if marker in d or marker in t:
            return True, f'Explicit multi-role/general marker found: "{marker}"'

    # 2. Cross-disciplinary multi-domain check (touching 3+ disjoint engineering pillars)
    domain_keywords = {
        "Embedded/Mobile/Systems": [
            "android", "aosp", "embedded", "soc", "firmware", "kernel", "sensor", "iot",
            "qualcomm", "device security", "keystore", "selinux", "hardware"
        ],
        "AI/ML/ComputerVision": [
            "deep learning", "computer vision", "nlp", "machine learning", "pytorch",
            "tensorflow", "llm", "generative ai", "gemini", "neural network"
        ],
        "Distributed/BigData/Cloud": [
            "kafka", "spark", "distributed system", "data streaming", "batch processing",
            "hadoop", "microservice", "distributed systems"
        ],
        "FullStack/Web/Backend": [
            "full stack", "fullstack", "react", "node.js", "typescript", "fastapi",
            "flask", "django", "rest api", "web application"
        ],
        "DevOps/Automation/Tooling": [
            "ci/cd", "docker", "kubernetes", "playwright", "automation", "test automation",
            "testing automation", "devops"
        ]
    }
    matched_domains = []
    for domain, kw_list in domain_keywords.items():
        if any(re.search(r"\b" + re.escape(kw) + r"\b", d) for kw in kw_list):
            matched_domains.append(domain)

    if len(matched_domains) >= 3:
        return True, f"Cross-disciplinary role touching {len(matched_domains)} domains: {', '.join(matched_domains)}"

    # 3. Vague/Sparse Description with generic title
    generic_titles = [
        "software engineer", "software developer", "member of technical staff", "associate software engineer",
        "engineering intern", "sde intern", "technology intern", "graduate engineer", "technology analyst"
    ]
    if any(gt in t for gt in generic_titles) and len(d.strip()) < 350:
        return True, f'Vague/sparse description ({len(d.strip())} chars) with generic title "{title}"'

    return False, "Targeted/domain-specific posting"


def tailor_materials(job_id: str, profile_name: str = "madhav"):
    db.init_db()
    profile = profiles.get_profile(profile_name)
    
    # Load resume
    resume_path = profile.resume_path
    if not os.path.exists(resume_path):
        if profile.id == "madhav" and os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "resume.md")):
            resume_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resume.md")
        else:
            print(f"Error: resume file {resume_path} not found.", file=sys.stderr)
            return None
        
    with open(resume_path, "r", encoding="utf-8") as f:
        resume_text = f.read()

    # Auto-ingest if job_id is a URL
    if job_id.startswith("http://") or job_id.startswith("https://"):
        import custom_job
        resolved_id = custom_job.ingest_custom_job(job_id)
        if not resolved_id:
            return None
        job_id = resolved_id

    # Fetch GitHub portfolio for this candidate profile
    print(f"-> Fetching {profile.name}'s GitHub portfolio for dynamic project alignment...")
    portfolio = github_portfolio.fetch_github_portfolio(profile=profile)
    if getattr(profile, "curated_projects", None):
        curated_lines = []
        for p_id, p_info in profile.curated_projects.items():
            curated_lines.append(f"### Project: {p_info.get('display_name', p_id)}")
            curated_lines.append(f"- **Repository**: {p_info.get('url', 'None')}")
            desc = p_info.get('description', '')
            if len(desc) > 320:
                desc = desc[:320].rstrip() + "..."
            curated_lines.append(f"- **Overview**: {desc}")
            curated_lines.append("")
        portfolio_text = "\n".join(curated_lines)
    else:
        portfolio_text = github_portfolio.format_github_portfolio_for_prompt(portfolio)
        
    # Get job details
    conn = db.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
    job = cursor.fetchone()
    conn.close()
    
    if not job:
        print(f"Error: Job ID {job_id} not found in database.", file=sys.stderr)
        return None
        
    title = job['title']
    company = job['company']
    description = job['description'] or ""
    
    print(f"Tailoring application materials for {profile.name}: '{title}' at '{company}'...")

    is_ambiguous, ambiguity_reason = is_job_description_ambiguous(title, description)
    if profile.id in ("secondary", "mahika", "partner"):
        if is_ambiguous:
            print(f"-> Ambiguous / multi-track role detected: {ambiguity_reason}")
            print("-> Applying Broad Versatility Strategy for Mahika: Selecting top 3 diverse projects across pillars...")
            project_strategy = f"""2. DYNAMIC PROJECT SELECTION & ALIGNMENT -- 1-PAGE CURATED STRATEGY (AMBIGUOUS / MULTI-TRACK):
    - DETECTED CONTEXT: The Job Posting is AMBIGUOUS, MULTI-TRACK, or a GENERAL HIRING POOL ({ambiguity_reason}).
    - CORE DIRECTIVE: Select EXACTLY the TOP 3 DIVERSE, HIGH-SIGNAL PROJECTS from Mahika's verified pool to showcase versatile technical breadth while fitting strictly on 1 page:
        * Project 1 (Full-Stack Flagship / AI / Database): 'Multi-Modal AI Protein Analysis & Pathogenicity Reasoning Platform' (GitHub: https://github.com/madhavofficial/neuro_capstone)
        * Project 2 (Enterprise Systems / Java / MySQL / FinTech OR Systems / C / OS): 'Enterprise Loan Management System' (GitHub: https://github.com/surabhi1828/LoanManagementSystem) OR 'Mini-UnionFS: Layered Union File System in C with FUSE' (GitHub: https://github.com/Mahika6/mini-unionfs)
        * Project 3 (ML / NLP / GenAI): 'Resume-JD Semantic Matcher & Explainable Screening Engine' (GitHub: https://github.com/Mahika6/genai-project) OR 'Interactive Deep Learning Drawing Classifier' (GitHub: https://github.com/madhavofficial/Drawing-A-New-Way-To-Search-ML-)
    - ANTI-CLUSTERING RULE: NEVER select both 'Enterprise Loan Management System' and 'Personal Wealth Management Application' on the same resume; choose at most one to prevent redundant domain clustering in finance.
    - For each selected project, write 2 concise, punchy, high-density bullet points (Bullet 1: WHAT it does; Bullet 2: architecture & verified metrics).
    - EXPANDED SKILLS: Ensure Technical Skills covers the languages and tools from the selected projects."""
        else:
            print("-> Targeted role detected for Mahika. Applying Deep Specialization Strategy...")
            project_strategy = """2. DYNAMIC PROJECT SELECTION & ALIGNMENT -- 1-PAGE CURATED STRATEGY (TARGETED ROLE):
    - Review the Job Posting requirements and select the BEST-FITTING projects from Mahika's verified pool:
        * CORE FLAGSHIP PRINCIPLE: 'Multi-Modal AI Protein Analysis & Pathogenicity Reasoning Platform' (GitHub: https://github.com/madhavofficial/neuro_capstone) is Mahika's primary technical flagship demonstrating modern full-stack web engineering (React 18, TypeScript, Vite, Tailwind CSS), high-performance API design (FastAPI), relational cloud databases (Supabase PostgreSQL with RLS), and rigorous benchmarking. STRONGLY PRIORITIZE including it across all AI/ML, Full-Stack, Web, TypeScript, React, Database, and general Software Engineering / IT Developer roles.
        * For Enterprise / Business Systems / FinTech / Banking / Java / Supply Chain roles -> PAIR 'Enterprise Loan Management System' (GitHub: https://github.com/surabhi1828/LoanManagementSystem; Java SE, MVC, MySQL, 5 GoF patterns, RBAC, financial compliance and auditing) with her full-stack flagship 'Multi-Modal AI Protein Analysis & Pathogenicity Reasoning Platform'.
        * ANTI-CLUSTERING RULE: NEVER select both 'Enterprise Loan Management System' and 'Personal Wealth Management Application' together on the same resume! Doing so causes repetitive domain clustering in finance. Choose at most one finance-specific project and pair it with a system of different architectural breadth (specifically 'neuro_capstone').
        * For AI / ML / GenAI / NLP / LLM roles -> STRONGLY PRIORITIZE:
          1. 'Multi-Modal AI Protein Analysis & Pathogenicity Reasoning Platform' (GitHub: https://github.com/madhavofficial/neuro_capstone)
          2. 'Resume-JD Semantic Matcher & Explainable Screening Engine' (GitHub: https://github.com/Mahika6/genai-project)
          3. 'Interactive Deep Learning Drawing Classifier' (GitHub: https://github.com/madhavofficial/Drawing-A-New-Way-To-Search-ML-)
        * For Systems / OS / C / Linux roles -> prioritize 'Mini-UnionFS: Layered Union File System in C with FUSE' (GitHub: https://github.com/Mahika6/mini-unionfs) paired with 'Enterprise Loan Management System' or 'neuro_capstone'.
        * For Robotics / Computer Vision -> prioritize 'Autonomous Robotics: Dual-Pipeline Visual Servoing & Odometry' (GitHub: https://github.com/surabhi1828/autonomous-detection-4wd-robot) and 'Interactive Deep Learning Drawing Classifier'.
    - For each selected project, write 2 concise, punchy, high-density bullet points (Bullet 1: WHAT it does; Bullet 2: architecture & verified metrics).
    - EXPANDED SKILLS: Highlight the exact languages, frameworks, and tools used across the 3 selected projects and experience."""
    elif is_ambiguous:
        print(f"-> Ambiguous / multi-track role detected: {ambiguity_reason}")
        print("-> Applying Broad Versatility Strategy: Selecting top 3 diverse projects across pillars...")
        project_strategy = f"""2. DYNAMIC PROJECT SELECTION & ALIGNMENT -- 1-PAGE CURATED STRATEGY (AMBIGUOUS / MULTI-TRACK):
    - DETECTED CONTEXT: The Job Posting is AMBIGUOUS, MULTI-TRACK, or a GENERAL HIRING POOL ({ambiguity_reason}).
    - CORE DIRECTIVE: Select EXACTLY the TOP 3 DIVERSE, HIGH-SIGNAL PROJECTS from the candidate's verified pool (Base Resume + GitHub Portfolio) to showcase versatile technical breadth while fitting strictly on 1 page:
        * Project 1 (AI / Multi-Agent / Research): 'GLAS-Med: Evidence-Grounded Clinical Literature Synthesis' (GitHub: https://github.com/madhavofficial/evidence-grounded-clinical-literature-synthesis) OR 'Multi-Modal AI Protein Analysis & Pathogenicity Reasoning Platform' (GitHub: https://github.com/madhavofficial/neuro_capstone)
        * Project 2 (Distributed Systems / Big Data / CV): 'Distributed High-Throughput Stream & Image Processing Pipeline with Apache Kafka' (GitHub: https://github.com/varunnhn/153_Project3_BD) OR 'Sketch Recognition System' (GitHub: https://github.com/madhavofficial/Drawing-A-New-Way-To-Search-ML-)
        * Project 3 (Full-Stack / Automation / FinTech): 'Smart Market Watchlist & Real-Time Trading Terminal' (GitHub: https://github.com/madhavofficial/Ultimate-Trader-Dashboard-GitHub-Repository-Structure) OR 'Autonomous Job Discovery, Career Intelligence & Application Automation Engine' (GitHub: https://github.com/madhavofficial/job-hunter) OR 'CareerTime - AI Career Intelligence Platform' (GitHub: https://github.com/madhavofficial/CareerTime)
    - For each selected project, write 2 to 3 concise, punchy, high-density bullet points (Bullet 1: WHAT it does; Bullets 2-3: architecture & metrics).
    - EXPANDED SKILLS: Ensure the Technical Skills section covers the languages and tools from the selected projects."""
    else:
        print("-> Targeted role detected. Applying Deep Specialization Strategy...")
        project_strategy = """2. DYNAMIC PROJECT SELECTION & ALIGNMENT -- 1-PAGE CURATED STRATEGY (TARGETED ROLE):
    - Carefully review the Job Posting requirements (required languages, frameworks, domain, e.g. DevOps, TypeScript, Full-Stack Web, Backend, Distributed Systems, AI/ML, Data Science, Databases).
    - Compare the candidate's Current Resume Projects with the candidate's Verified GitHub Project Portfolio.
    - Select EXACTLY the TOP 3 BEST-FITTING projects from the combined pool of projects (Current Resume + GitHub Portfolio).
    - Alignment recommendations:
        * For AI / RAG / Agent / NLP / Generative AI / Research / Machine Learning / Applied AI roles -> STRONGLY PRIORITIZE:
          1. 'Multi-Modal AI Protein Analysis & Pathogenicity Reasoning Platform' (GitHub: https://github.com/madhavofficial/neuro_capstone)
          2. 'CareerTime - AI Career Intelligence Platform' (GitHub: https://github.com/madhavofficial/CareerTime)
          3. 'Autonomous Job Discovery, Career Intelligence & Application Automation Engine' (GitHub: https://github.com/madhavofficial/job-hunter) OR 'Sketch Recognition System' (GitHub: https://github.com/madhavofficial/Drawing-A-New-Way-To-Search-ML-)
          CRITICAL: NEVER include 'Mini-UnionFS' on an AI, ML, Data, or Web/Application engineering resume! 'Mini-UnionFS' is a C/FUSE filesystem project that is completely irrelevant to AI/ML and is strictly reserved for Systems / OS / Kernel / C / C++ / Embedded systems roles.
        * For Systems / OS / C / C++ / Embedded / Linux / Filesystems / Networking / Wireless / Cellular roles -> STRONGLY PRIORITIZE 'Mini-UnionFS: Layered Union File System in C with FUSE' (GitHub: https://github.com/madhavofficial/mini-unionfs) paired with 'GLAS-Med: Evidence-Grounded Clinical Literature Synthesis' and 'Autonomous Job Discovery, Career Intelligence & Application Automation Engine' or 'Multi-Modal AI Protein Analysis & Pathogenicity Reasoning Platform'.
        * For Quality Engineering / SDET / Test Automation / QE / GenAI Testing roles -> STRONGLY PRIORITIZE 'Autonomous Job Discovery, Career Intelligence & Application Automation Engine' (GitHub: https://github.com/madhavofficial/job-hunter), 'Mini-UnionFS: Layered Union File System in C with FUSE' (GitHub: https://github.com/madhavofficial/mini-unionfs), and 'GLAS-Med: Evidence-Grounded Clinical Literature Synthesis' (GitHub: https://github.com/madhavofficial/evidence-grounded-clinical-literature-synthesis).
        * CRITICAL ANTI-DUPLICATION RULE: 'GLAS-Med: Evidence-Grounded Clinical Literature Synthesis' and 'Multi-Agent Generative AI System for Scientific Literature Analysis' (IEEE SPICES) are the SAME research project. The IEEE SPICES paper belongs STRICTLY under '## Publications'. NEVER list 'Multi-Agent Generative AI System for Scientific Literature Analysis' under '## Selected Projects'! NEVER select both 'GLAS-Med' and 'Multi-Agent Generative AI System' as separate projects on the same resume.
        * For DevOps / Cloud / Automation / Tooling roles -> prioritize 'Autonomous Job Discovery, Career Intelligence & Application Automation Engine' (GitHub: https://github.com/madhavofficial/job-hunter).
        * For Big Data / Data Engineering / Streaming / Kafka / Distributed Systems -> prioritize 'Distributed High-Throughput Stream & Image Processing Pipeline with Apache Kafka' (GitHub: https://github.com/varunnhn/153_Project3_BD) and 'Hourly Bike-Sharing Demand Forecasting & Time-Series Regression Pipeline' (GitHub: https://github.com/madhavofficial/Forecasting-Bike-Rental-Demand).
        * For Full-Stack / TypeScript / FinTech / Database roles -> prioritize 'Smart Market Watchlist & Real-Time Trading Terminal' (GitHub: https://github.com/madhavofficial/Ultimate-Trader-Dashboard-GitHub-Repository-Structure).
        * For Computer Vision / Deep Learning -> prioritize 'Sketch Recognition System' (GitHub: https://github.com/madhavofficial/Drawing-A-New-Way-To-Search-ML-).
        * For Data Science / Regression / Analytics -> prioritize 'Hourly Bike-Sharing Demand Forecasting & Time-Series Regression Pipeline' (GitHub: https://github.com/madhavofficial/Forecasting-Bike-Rental-Demand).
    - BULLET WRITING DIRECTIVE (NO ROBOTIC META-LABELS):
      * For each selected project, write EXACTLY 2 concise, punchy, high-density bullet points.
      * NEVER prefix bullets with meta-labels like '**What it does**:', '**Architecture & Impact**:', '**Overview**:', '**Impact**:', or '**Architecture**:'.
      * Start each bullet directly with an active past-tense engineering verb (e.g. 'Architected...', 'Engineered...', 'Developed...', 'Trained...', 'Implemented...').
      * Bullet 1: Core capabilities, algorithmic/product functionality, and what the system accomplishes.
      * Bullet 2: Architecture, frameworks/libraries used, pipeline design, and verified performance/accuracy metrics.
    - EXPANDED SKILLS: Highlight the exact languages, frameworks, and tools used across the 3 selected projects and experience."""
    
    # Init Groq
    from dotenv import load_dotenv
    load_dotenv()
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("Error: GROQ_API_KEY not found.", file=sys.stderr)
        return None
        
    client = Groq(api_key=api_key)
    model_name = config.get_best_model(client)
    print(f"Using Groq model: {model_name}")
    
    # Create tailored directory
    tailored_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tailored")
    os.makedirs(tailored_dir, exist_ok=True)
    
    if profile.id == "madhav":
        length_curation_instruction = """4. STRICT 1-PAGE TARGET & SPECIALLY CURATED SELECTION:
   - TARGET EXACTLY 1 PAGE: The tailored resume MUST fit cleanly onto EXACTLY ONE PAGE when compiled with LaTeX.
   - EDUCATION: MUST always include '## Education' with PES University, B.Tech in Computer Science and Engineering (Expected May 2027) and relevant coursework.
   - CURATED PROJECT SELECTION: Select EXACTLY the TOP 3 BEST-FITTING projects for this role from the candidate's verified pool (EXACTLY 2 concise, punchy bullets per project). DO NOT include more than 3 projects under any circumstances.
   - CONDENSED PROFESSIONAL EXPERIENCE:
     * Condense Qualcomm into EXACTLY 3 high-impact bullets focusing on autonomous agents, Claude Code Skills, MCP integrations, Jira/Splunk automation, and Pydantic guardrails.
     * Condense O.C. Tanner into EXACTLY 2 bullets (Kotlin accessibility Jira tickets, 10% to 70% automated test coverage across Scala/Android).
   - CONDENSED PUBLICATIONS:
     * In '## Publications', include the IEEE SPICES paper condensed into EXACTLY 2 high-impact bullets focusing on technical functionality and system architecture:
       - Bullet 1 (Retrieval & Ingestion): Built an evidence-grounded multi-agent system querying scholarly APIs (arXiv, PubMed, Semantic Scholar) and ingesting 300-800 papers per query with automated hallucination guardrails to eliminate false citations.
       - Bullet 2 (Graph Clustering & Ensemble): Applied semantic Louvain graph clustering to partition literature into thematic sub-corpora and coordinated a 5-agent ensemble to extract empirical claims, evaluate methodology, and cross-examine evidence to resolve contradictions across papers.
       - DO NOT output abstract or context-free percentage metrics (e.g. '92.7% accuracy / 89.8% F1')—focus strictly on what the system does, the multi-agent coordination, and the contradiction resolution mechanism.
   - CAREER OBJECTIVE: Keep the Career Objective to a crisp, dynamic 2-sentence punch: "Employment-ready Computer Science engineer specializing in backend systems and autonomous AI workflows. Seeking Software Engineering roles to build resilient, production-grade software and distributed solutions." (Tailor the technical domain specialization concisely to the role, but NEVER mention the company name or target position).
   - ZERO HARDWARE / NON-CS FABRICATION: Candidate is strictly a Computer Science and Engineering (CSE) student. NEVER claim grounding in analog circuits, circuit design, high-speed board design, PCB, or FPGA development. For telecom or embedded postings, frame interest and experience strictly around Embedded Software, C/C++, Linux systems programming, device interfacing, and OS internals.
   - CERTIFICATIONS: Do NOT include any Certifications section under any circumstances.
   - ZERO FACT FABRICATION: Rely strictly on facts and verified metrics in the source material."""
        ambiguity_eval_instruction = """   - 1-PAGE CONSTRAINT PRIORITY: Even if the role is broad, general development centre (IDC), or rotational, maintain the 1-PAGE limit by selecting exactly the top 3 projects across different domains."""
    elif profile.id in ("secondary", "mahika", "partner"):
        length_curation_instruction = """4. STRICT 1-PAGE TARGET & SPECIALLY CURATED SELECTION:
   - TARGET EXACTLY 1 PAGE: The tailored resume MUST fit cleanly onto EXACTLY ONE PAGE when compiled with LaTeX.
   - EDUCATION: MUST always include '## Education' with PES University, B.Tech in Computer Science and Engineering (Expected May 2027) and relevant coursework.
   - CURATED PROJECT SELECTION: Select EXACTLY the TOP 3 BEST-FITTING projects for this role from the candidate's verified pool (2 concise, punchy bullets per project). DO NOT include more than 3 projects under any circumstances.
   - CONDENSED PROFESSIONAL EXPERIENCE:
     * DRDO (Research Intern - AI-Based Radar Emitter Identification): Condense into 3 high-impact bullets focusing on the geometry-based PDW simulator modeling 150 concurrent emitters, PRI/RF clustering de-interleaving, LSTM sequence classifier (94.2% accuracy, 95.1% precision, 94.2% recall, 94.2% F1 score), and rule-based ECM recommendation layer.
   - LEADERSHIP & EXTRACURRICULAR:
     * In '## Leadership and Experience', include ONLY 1 concise bullet for Teaching Assistant (Python Programming Lab, PES University) and 1 concise bullet for Head of Social Media (TAMS).
     * DO NOT duplicate Teaching Assistant or TAMS under '## Professional Experience'. Under '## Professional Experience', include ONLY DRDO.
     * In '## Extracurricular Activities', include ONLY 1 line: 15+ years Classical Dance (Bharatanatyam).
   - CAREER OBJECTIVE: Keep the Career Objective to a crisp, dynamic 2-sentence punch: "Employment-ready Computer Science engineer specializing in machine learning, full-stack systems, and data pipelines. Seeking engineering roles to build resilient, production-grade software and high-impact solutions." (Tailor the technical domain specialization concisely to the role, but NEVER mention the company name or target position).
   - ZERO HARDWARE / NON-CS FABRICATION: Candidate is strictly a Computer Science and Engineering (CSE) student. NEVER claim grounding in analog circuits, circuit design, high-speed board design, PCB, or FPGA development. For telecom or embedded postings, frame interest and experience strictly around Embedded Software, C/C++, Linux systems programming, device interfacing, and OS internals.
   - CERTIFICATIONS: Do NOT include any Certifications section under any circumstances.
   - ZERO FACT FABRICATION: Rely strictly on facts and verified metrics in the source material."""
        ambiguity_eval_instruction = """   - 1-PAGE CONSTRAINT PRIORITY: Even if the role is broad, general development centre (IDC), or rotational, maintain the 1-PAGE limit by selecting exactly the top 3 projects across different domains."""
    else:
        length_curation_instruction = f"""4. ZERO METRIC OR FACT FABRICATION & NO LENGTH RESTRICTIONS:
   - Do NOT invent non-existent projects, companies, durations, graduation date (May 2027), or credentials. Rely strictly on facts in the candidate's resume and project portfolio.
   - ABSOLUTE BAN ON FABRICATED NUMBERS & METRICS: ONLY cite quantitative metrics (percentages, accuracy, latency, scale, test coverage, counts) that appear verbatim in the candidate's base resume or portfolio. If a project or role does not have a metric in the source material, explain the engineering architecture and algorithms -- NEVER invent numbers.
   - DO NOT invent unverified frameworks or integrations (e.g. do not invent SAP/ERP integrations or FastAPI if not present in the base resume or portfolio).
   - {profile.gpa_instruction} {profile.certifications_instruction}
   - There is NO artificial 1-page restriction - prioritize thorough understanding, architectural depth, and complete explanations over resume length. It is much more important that the reader understands the project than the size of the resume."""
        ambiguity_eval_instruction = """   - AUTONOMOUS AMBIGUITY EVALUATION: If the prompt marked this as targeted, but YOU evaluate from the Job Description that the role is actually broad, multi-track, general development centre (e.g. IDC), rotational, or lacks specific single-domain constraints, OVERRIDE and apply the AMBIGUOUS / BROAD JOB DIRECTIVE: include 4 to 5 diverse projects with 3-4 detailed, high-density bullets per project to showcase maximum engineering breadth."""

    # Tailor Resume Prompt
    resume_prompt = f"""You are an expert resume optimizer and technical hiring specialist. Your task is to adapt the candidate's resume for a specific job posting.

Instructions & Rules:
{profile.experience_instruction}
{project_strategy}
{ambiguity_eval_instruction}
{profile.flagship_instruction}
3. SKILLS SECTION: {profile.skills_instruction}
{length_curation_instruction}
5. FORMATTING & TYPOGRAPHY:
   - Heavily utilize markdown bolding (**bold**) for all key metrics, numbers, core technologies, and frameworks across every bullet point.
   - GITHUB REPOSITORY LINKS RULE:
     * Under `## Selected Projects`, ONLY include a `*GitHub: <url>*` line beneath a project title IF that project has an explicit, verified GitHub repository URL in the candidate's Verified Project Portfolio below.
     * NEVER invent, guess, or fabricate GitHub URLs (e.g. NEVER use /Portfolio or guess repo names). If a project does not have a verified repository or its repository is None, DO NOT include a `*GitHub: ...*` line for it at all.
     * When a verified repository exists, place it on the line immediately beneath the title:
       `### Project Name (Core Technologies)`
       `*GitHub: https://github.com/...*`
   - CERTIFICATIONS POLICY:
     * {profile.certifications_instruction}
   - ABSOLUTE BAN ON META-COMMENTARY:
     * NEVER include notes, footnotes, disclaimers, or compilation remarks anywhere in the resume (e.g. NEVER output 'This resume is formatted to fit a single page when compiled with LaTeX', 'Note:', or formatting remarks). Output ONLY the resume content itself.
   - Output the COMPLETE tailored resume in clean, professional Markdown.

Candidate Base Resume:
{resume_text}

Candidate's Verified Project Portfolio:
{portfolio_text}

Job Posting:
Company: {company}
Title: {title}
Description:
{description[:2200]}

Please output the COMPLETE tailored resume in Markdown.
"""

    try:
        # Generate Resume
        tailored_resume = None

        # 1. Primary: Groq Multi-Key & Frontier Model Cluster (sub-second inference)
        print("-> Generating tailored resume via Groq multi-key cluster...", flush=True)
        candidate_models = [model_name] + [m for m in config.get_fallback_models() if m != model_name]
        max_tokens_val = 2048
        for active_model in candidate_models:
            retries = 0
            max_retries = max(1, config.key_manager.get_num_keys())
            while retries < max_retries:
                try:
                    kwargs = {
                        "model": active_model,
                        "messages": [{"role": "user", "content": resume_prompt}],
                        "temperature": 0.2,
                        "max_tokens": max_tokens_val,
                        "timeout": 45,
                    }
                    if "gpt-oss" in active_model:
                        kwargs["reasoning_effort"] = "low"
                    res_response = client.chat.completions.create(**kwargs)
                    content = res_response.choices[0].message.content or ""
                    finish_reason = getattr(res_response.choices[0], "finish_reason", "")
                    if finish_reason == "length" or "technical skills" not in content.lower():
                        print(f"Warning: Model {active_model} generated incomplete/truncated response (finish_reason={finish_reason}). Trying next model...")
                        break
                    tailored_resume = content
                    break
                except Exception as e:
                    err_str = str(e).lower()
                    if "expired_api_key" in err_str or ("401" in err_str and "invalid api key" in err_str):
                        print(f"Invalid API key encountered. Dropping key and cycling...")
                        client = config.cycle_groq_client(remove_current=True)
                        retries += 1
                        continue

                    # If model is not available on this specific key, cycle to another key that has it
                    if any(term in err_str for term in ["model_not_found", "does not exist", "do not have access", "not found"]):
                        retries += 1
                        if retries < max_retries:
                            print(f"Model {active_model} not available on current key. Cycling to next key ({retries}/{max_retries})...")
                            client = config.cycle_groq_client()
                            continue
                    elif "rate_limit_exceeded" in err_str or "429" in err_str:
                        retries += 1
                        if retries < max_retries:
                            print(f"Rate limit hit on model {active_model}. Cycling key ({retries}/{max_retries})...")
                            client = config.cycle_groq_client()
                            continue
                    else:
                        print(f"Warning: Groq model {active_model} failed: {e}", file=sys.stderr)
                        break
            if tailored_resume:
                print(f"-> Successfully tailored resume using Groq ({active_model}).")
                break


        # 2. Secondary Fallback: OpenRouter Free-Tier (probe-verified 2026-09-29)
        if not tailored_resume:
            print("Warning: Groq cluster exhausted. Falling back to OpenRouter free tier...", file=sys.stderr)
            openrouter_key = os.getenv("OPENROUTER_API_KEY")
            if openrouter_key:
                from openai import OpenAI
                or_client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=openrouter_key, timeout=60)
                configured_openrouter_model = os.getenv("OPENROUTER_MODEL")
                openrouter_models = ([configured_openrouter_model] if configured_openrouter_model else list(PREFERRED_OPENROUTER_MODELS))
                for openrouter_model in openrouter_models:
                    try:
                        print(f"-> Trying OpenRouter fallback model: {openrouter_model}")
                        or_resp = or_client.chat.completions.create(
                            model=openrouter_model,
                            messages=[{"role": "user", "content": resume_prompt}],
                            temperature=0.2,
                            max_tokens=4096,
                            timeout=25,
                        )
                        if or_resp and or_resp.choices and or_resp.choices[0].message and or_resp.choices[0].message.content:
                            tailored_resume = or_resp.choices[0].message.content.strip()
                            if "technical skills" in tailored_resume.lower():
                                print(f"-> Successfully tailored resume using OpenRouter ({openrouter_model}).")
                                break
                            tailored_resume = None
                    except Exception as e:
                        print(f"Warning: OpenRouter model {openrouter_model} failed: {e}", file=sys.stderr)

        if not tailored_resume:
            raise ValueError("Failed to generate tailored resume after trying Groq cluster and OpenRouter fallbacks.")


        if not getattr(profile, "include_certifications", False):
            tailored_resume = strip_certifications(tailored_resume)
        tailored_resume = ensure_selected_project_github_links(tailored_resume, portfolio, profile=profile)
        tailored_resume = ensure_publication_links(tailored_resume)
        tailored_resume = ensure_career_objective_target(tailored_resume, company, title)
        tailored_resume = ensure_education(tailored_resume, profile=profile)
        tailored_resume = ensure_gpa(tailored_resume, profile=profile)
        tailored_resume = scrub_unverified_metrics(tailored_resume, profile_id=getattr(profile, "id", ""))
        tailored_resume = strip_meta_commentary(tailored_resume)
        tailored_resume = strip_robotic_bullet_labels(tailored_resume)
        if getattr(profile, "id", "") in ["madhav", "secondary", "partner", "mahika"]:
            tailored_resume = enforce_one_page_budget(tailored_resume, profile_id=getattr(profile, "id", "madhav"))
        
        # Save files in dedicated company directory with <profile.file_prefix>_ naming scheme
        clean_company = "".join([c for c in company if c.isalnum() or c in (' ', '_')]).replace(' ', '_')
        clean_title = "".join([c for c in title if c.isalnum() or c in (' ', '_')]).replace(' ', '_')
        clean_company = re.sub(r'_+', '_', clean_company).strip('_')
        clean_title = re.sub(r'_+', '_', clean_title).strip('_')

        company_dir = os.path.join(tailored_dir, clean_company)
        os.makedirs(company_dir, exist_ok=True)

        resume_filename = f"{profile.file_prefix}_{clean_company}_{clean_title}_Resume.md"
        resume_pdf_filename = f"{profile.file_prefix}_{clean_company}_{clean_title}_Resume.pdf"
        resume_tex_filename = f"{profile.file_prefix}_{clean_company}_{clean_title}_Resume.tex"

        resume_filepath = os.path.join(company_dir, resume_filename)
        resume_pdf_filepath = os.path.join(company_dir, resume_pdf_filename)
        resume_tex_filepath = os.path.join(company_dir, resume_tex_filename)

        with open(resume_filepath, "w", encoding="utf-8") as f:
            f.write(tailored_resume)

        # High-grade LaTeX / Tectonic compilation with automatic ReportLab fallback
        import latex_utils
        tex_content = latex_utils.markdown_to_latex(tailored_resume)
        with open(resume_tex_filepath, "w", encoding="utf-8") as f:
            f.write(tex_content)

        compiled_with_tectonic = latex_utils.compile_latex_to_pdf(tex_content, resume_pdf_filepath, resume_tex_filepath)
        if compiled_with_tectonic and getattr(profile, "id", "") in ["madhav", "secondary", "partner", "mahika"]:
            import subprocess
            try:
                p_info = subprocess.run(["pdfinfo", resume_pdf_filepath], capture_output=True, text=True)
                m_pages = re.search(r"Pages:\s+(\d+)", p_info.stdout)
                if m_pages and int(m_pages.group(1)) > 1:
                    print(f"Warning: Compiled PDF has {m_pages.group(1)} pages. Applying strict 1-page compression...")
                    tailored_resume = enforce_one_page_budget(tailored_resume, profile_id=getattr(profile, "id", "madhav"), strict_mode=True)
                    with open(resume_filepath, "w", encoding="utf-8") as f:
                        f.write(tailored_resume)
                    tex_content = latex_utils.markdown_to_latex(tailored_resume)
                    with open(resume_tex_filepath, "w", encoding="utf-8") as f:
                        f.write(tex_content)
                    latex_utils.compile_latex_to_pdf(tex_content, resume_pdf_filepath, resume_tex_filepath)
            except Exception as e:
                print(f"Page check error: {e}")

        if not compiled_with_tectonic:
            markdown_to_pdf(tailored_resume, resume_pdf_filepath, engine="reportlab")

        print(f"-> Tailored Resume saved to: {resume_filepath}")
        print(f"-> LaTeX Source saved to: {resume_tex_filepath}")
        print(f"-> ATS Resume PDF saved to: {resume_pdf_filepath}")
        
        # Store generated materials in database (only for default profile)
        if profile.id == "madhav":
            db.store_tailored_materials(job_id, resume_filepath, None, resume_pdf_filepath, None)
        
        return resume_filepath, resume_pdf_filepath
        
    except Exception as e:
        print(f"Error generating tailored materials: {e}", file=sys.stderr)
        return None

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Tailor application materials for a job listing")
    parser.add_argument("job_id", help="Job ID or URL to tailor for")
    parser.add_argument("--profile", "-p", default="madhav", help="Candidate profile (e.g. 'madhav', 'mahika')")
    args = parser.parse_args()
    tailor_materials(args.job_id, profile_name=args.profile)
