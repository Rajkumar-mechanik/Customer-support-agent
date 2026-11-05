"""Design tokens and CSS for the support console.

Direction: a service-desk console for a consumer-electronics store. A deep teal rail carries the
brand (the amber point of light is the one decorative accent); the working area is a cool, pale
workbench; status is communicated with two unmistakable colours only (green resolved, red escalated).
The memorable element is the case file: an index-card whose spine takes the colour of the outcome.
"""

TOKENS = {
    "ink": "#13222B",
    "ink_soft": "#4A5C66",
    "rail": "#0D2A31",
    "rail_text": "#C9DADD",
    "bench": "#E8EDF0",
    "surface": "#FFFFFF",
    "line": "#D3DCE1",
    "amber": "#F2A81D",
    "resolved": "#1C7C4B",
    "resolved_bg": "#E4F3EA",
    "escalated": "#B3261E",
    "escalated_bg": "#FBE8E6",
    "running": "#C98400",
}

FONT_IMPORT = (
    "@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700"
    "&family=Hanken+Grotesk:wght@400;500;600;700&display=swap');"
)


def css() -> str:
    t = TOKENS
    return f"""
{FONT_IMPORT}
:root {{
  --ink: {t['ink']}; --ink-soft: {t['ink_soft']}; --rail: {t['rail']}; --rail-text: {t['rail_text']};
  --bench: {t['bench']}; --surface: {t['surface']}; --line: {t['line']}; --amber: {t['amber']};
  --resolved: {t['resolved']}; --resolved-bg: {t['resolved_bg']};
  --escalated: {t['escalated']}; --escalated-bg: {t['escalated_bg']}; --running: {t['running']};
  --display: 'Bricolage Grotesque', 'Hanken Grotesk', system-ui, sans-serif;
  --body: 'Hanken Grotesk', system-ui, -apple-system, 'Segoe UI', sans-serif;
}}

html, body, .stApp, [class*="st-"] {{ font-family: var(--body); }}
.stApp {{ background: var(--bench); color: var(--ink); }}
#MainMenu, footer, [data-testid="stDecoration"], [data-testid="stToolbar"] {{ visibility: hidden; height: 0; }}
.block-container {{ padding: 2.2rem 2.6rem 4rem; max-width: 1240px; }}
h1, h2, h3 {{ font-family: var(--display); color: var(--ink); letter-spacing: -0.015em; }}
p, li, label, .stMarkdown {{ color: var(--ink); }}
a {{ color: var(--ink); }}

/* ---------- rail (sidebar) ---------- */
[data-testid="stSidebar"] {{ background: var(--rail); min-width: 270px; max-width: 270px; }}
[data-testid="stSidebar"] * {{ color: var(--rail-text); }}
[data-testid="stSidebar"] .block-container, [data-testid="stSidebarUserContent"] {{ padding: 1.6rem 1.2rem; }}
.wordmark {{ font-family: var(--display); font-weight: 700; font-size: 1.55rem; color: #fff !important; letter-spacing: -0.02em; display: flex; align-items: center; gap: 10px; }}
.wordmark .bulb {{ width: 12px; height: 12px; border-radius: 50%; background: var(--amber); box-shadow: 0 0 0 4px rgba(242,168,29,0.22), 0 0 18px rgba(242,168,29,0.55); flex: none; }}
.wordmark-sub {{ margin: 4px 0 26px 22px; font-size: 0.86rem; color: #8FB0B6 !important; }}
[data-testid="stSidebar"] [role="radiogroup"] {{ gap: 2px; }}
[data-testid="stSidebar"] [role="radiogroup"] label {{ padding: 9px 12px; border-radius: 6px; width: 100%; cursor: pointer; }}
[data-testid="stSidebar"] [role="radiogroup"] label:hover {{ background: rgba(255,255,255,0.06); }}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{ background: rgba(255,255,255,0.10); box-shadow: inset 3px 0 0 var(--amber); }}
[data-testid="stSidebar"] [role="radiogroup"] label > div:first-child {{ display: none; }}
[data-testid="stSidebar"] [role="radiogroup"] p {{ font-weight: 600; font-size: 0.97rem; color: #fff !important; }}
.sysbox {{ margin-top: 30px; padding-top: 16px; border-top: 1px solid rgba(255,255,255,0.12); font-size: 0.86rem; line-height: 1.9; }}
.sysbox .row {{ display: flex; justify-content: space-between; gap: 10px; }}
.sysbox .k {{ color: #8FB0B6 !important; }}
.sysbox .v {{ color: #fff !important; font-weight: 600; text-align: right; }}
.sysbox .dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 7px; }}
.dot.ok {{ background: #4CC38A; }} .dot.warn {{ background: var(--amber); }} .dot.bad {{ background: #FF6B5F; }}

/* ---------- page header ---------- */
.page-title {{ font-family: var(--display); font-weight: 700; font-size: 2.05rem; letter-spacing: -0.025em; margin: 0 0 4px; }}
.page-sub {{ color: var(--ink-soft); font-size: 1.02rem; margin: 0 0 1.6rem; max-width: 62ch; }}

/* ---------- panels ---------- */
.panel-title {{ font-family: var(--display); font-weight: 700; font-size: 1.12rem; margin: 0 0 12px; }}
[data-testid="stForm"] {{ background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 1.3rem 1.3rem 1rem; }}
[data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea, [data-baseweb="select"] > div {{
  background: #F7F9FA; border-color: var(--line); color: var(--ink); border-radius: 6px; }}
[data-testid="stTextInput"] input:focus, [data-testid="stTextArea"] textarea:focus {{ border-color: var(--rail); box-shadow: 0 0 0 2px rgba(242,168,29,0.55); }}
[data-testid="stTextInput"] label, [data-testid="stTextArea"] label, [data-testid="stSelectbox"] label {{ font-weight: 600; font-size: 0.92rem; }}
.stButton > button, [data-testid="stFormSubmitButton"] > button, .stDownloadButton > button {{
  width: 100%; border-radius: 6px; font-weight: 600; font-family: var(--body); border: 1px solid var(--rail); }}
[data-testid="stFormSubmitButton"] > button[kind="primaryFormSubmit"], .stButton > button[kind="primary"] {{ background: var(--rail); color: #fff; }}
[data-testid="stFormSubmitButton"] > button:hover, .stButton > button:hover {{ border-color: var(--amber); box-shadow: 0 0 0 2px rgba(242,168,29,0.45); }}
.stDownloadButton > button {{ background: var(--surface); color: var(--ink); }}
:focus-visible {{ outline: 2px solid var(--amber); outline-offset: 2px; }}

/* ---------- pipeline timeline ---------- */
.pipeline {{ background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 1.2rem 1.4rem 0.6rem; margin-bottom: 1.1rem; }}
.step {{ position: relative; padding: 0 0 18px 30px; }}
.step::before {{ content: ""; position: absolute; left: 8px; top: 18px; bottom: -2px; width: 2px; background: var(--line); }}
.step:last-child::before {{ display: none; }}
.step .node {{ position: absolute; left: 0; top: 3px; width: 18px; height: 18px; border-radius: 50%; border: 2px solid var(--line); background: var(--surface); }}
.step.done .node {{ background: var(--resolved); border-color: var(--resolved); }}
.step.done::before {{ background: var(--resolved); }}
.step.run .node {{ border-color: var(--running); background: var(--surface); box-shadow: 0 0 0 4px rgba(201,132,0,0.18); }}
.step.fail .node {{ background: var(--escalated); border-color: var(--escalated); }}
.step.skip .node {{ border-style: dashed; }}
.step.skip .name {{ color: var(--ink-soft); }}
.step .name {{ font-weight: 700; font-size: 0.98rem; }}
.step .time {{ float: right; color: var(--ink-soft); font-size: 0.84rem; font-variant-numeric: tabular-nums; }}
.step .role {{ color: var(--ink-soft); font-size: 0.88rem; }}
.step .out {{ margin-top: 4px; font-size: 0.93rem; background: #F2F5F7; border-radius: 5px; padding: 6px 10px; }}
.notes {{ font-size: 0.86rem; color: var(--ink-soft); padding: 0 0 12px 30px; }}

/* ---------- case file (result) ---------- */
.casefile {{ background: var(--surface); border: 1px solid var(--line); border-left: 8px solid var(--ink-soft); border-radius: 8px; padding: 1.3rem 1.5rem 1.4rem; }}
.casefile.resolved {{ border-left-color: var(--resolved); }}
.casefile.escalated {{ border-left-color: var(--escalated); }}
.cf-head {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; }}
.cf-id {{ font-family: var(--display); font-weight: 700; font-size: 1.9rem; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; }}
.badge {{ display: inline-block; padding: 5px 14px; border-radius: 4px; font-weight: 700; font-size: 0.93rem; border: 1.5px solid; }}
.badge.resolved {{ color: var(--resolved); background: var(--resolved-bg); border-color: var(--resolved); }}
.badge.escalated {{ color: var(--escalated); background: var(--escalated-bg); border-color: var(--escalated); }}
.facts {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 0; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); margin-bottom: 16px; }}
.fact {{ padding: 10px 12px 10px 0; }}
.fact + .fact {{ padding-left: 14px; border-left: 1px solid var(--line); }}
.fact .l {{ color: var(--ink-soft); font-size: 0.82rem; }}
.fact .v {{ font-weight: 700; font-size: 1.02rem; font-variant-numeric: tabular-nums; }}
.sec-label {{ font-weight: 700; font-size: 0.9rem; color: var(--ink-soft); margin: 14px 0 6px; }}
.reply {{ background: #F7F9FA; border: 1px solid var(--line); border-radius: 6px; padding: 16px 18px; line-height: 1.6; font-size: 0.98rem; max-width: 70ch; }}
.reply p {{ margin: 0 0 0.85em; }}
.reply p:last-child {{ margin-bottom: 0; }}
.reasons {{ margin: 0; padding-left: 1.2rem; }}
.reasons li {{ margin: 2px 0; }}
.sources {{ display: flex; flex-wrap: wrap; gap: 6px; }}
.src {{ border: 1px solid var(--line); background: #F2F5F7; border-radius: 4px; padding: 2px 9px; font-size: 0.86rem; font-variant-numeric: tabular-nums; }}
.empty {{ background: var(--surface); border: 1px dashed #B5C2C9; border-radius: 8px; padding: 1.5rem 1.6rem; color: var(--ink-soft); }}
.empty b {{ color: var(--ink); }}

/* ---------- evidence ---------- */
.ev {{ border-top: 1px solid var(--line); padding: 10px 0; }}
.ev:first-child {{ border-top: 0; }}
.ev .h {{ font-weight: 700; font-size: 0.92rem; }}
.ev .cov {{ height: 4px; background: var(--line); border-radius: 2px; margin: 5px 0 7px; width: 160px; }}
.ev .cov i {{ display: block; height: 100%; background: var(--rail); border-radius: 2px; }}
.ev .t {{ font-size: 0.9rem; color: var(--ink-soft); }}

/* ---------- metrics ---------- */
[data-testid="stMetric"] {{ background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 14px 16px; }}
[data-testid="stMetricValue"] {{ font-family: var(--display); font-weight: 700; }}

@media (max-width: 900px) {{
  .block-container {{ padding: 1.2rem 1rem 3rem; }}
  .facts {{ grid-template-columns: 1fr 1fr; }}
  .fact:nth-child(3) {{ border-left: 0; padding-left: 0; }}
}}
@media (prefers-reduced-motion: no-preference) {{
  .step .node {{ transition: background .2s, border-color .2s, box-shadow .2s; }}
}}
"""
