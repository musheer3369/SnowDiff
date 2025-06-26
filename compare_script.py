import json
import os
import requests
import xml.etree.ElementTree as ET
import jsbeautifier
import difflib
from collections import defaultdict

# ==================== Load config ====================

with open('config.json', encoding='utf-8-sig') as f:
    config = json.load(f)

INSTANCE1 = config['instances']['instance1']
INSTANCE2 = config['instances']['instance2']
TABLES = config['tables']
QUERY = config['query']
OUTPUT_DIR = config['output_dir']

# ==================== Helper Functions ====================

def clean_text(text: str) -> str:
    return text.replace('\ufeff', '').replace('\u200b', '').strip()

def get_records(host: str, user: str, password: str, table: str, query: str):
    url = f"https://{host}.service-now.com/api/now/table/{table}"
    resp = requests.get(
        url, auth=(user, password),
        params={"sysparm_query": query, "sysparm_limit": "1000"}
    )
    resp.raise_for_status()
    return resp.json().get('result', [])

def fetch_xml(host: str, table: str, sys_id: str, user: str, password: str) -> ET.Element:
    url = f"https://{host}.service-now.com/{table}.do?XML&sys_id={sys_id}"
    resp = requests.get(url, auth=(user, password))
    resp.raise_for_status()
    return ET.fromstring(resp.content)

def extract_all_tags(root: ET.Element) -> dict:
    record_node = list(root)[0]
    result = {}
    for child in record_node:
        text = child.text or ""
        if "script" in child.tag.lower():
            text = jsbeautifier.beautify(text, jsbeautifier.default_options())
        result[child.tag] = clean_text(text)
    return result

def generate_side_by_side_diff_html(text1: str, text2: str) -> str:
    diff_table = difflib.HtmlDiff(tabsize=4, wrapcolumn=80).make_table(
        text1.splitlines(),
        text2.splitlines(),
        fromdesc='Instance1',
        todesc='Instance2',
        context=False
    )
    style = """
    <style>
    table.diff { font-family: monospace; font-size: 0.8rem; border-collapse: collapse; width: 100%; }
    .diff_add { background-color: #d4fcbc; }
    .diff_chg { background-color: #fff3bf; }
    .diff_sub { background-color: #fbb6b6; }
    </style>
    """
    return style + diff_table

def wrap_html_report(all_sections_html: str, summary_html: str) -> str:
    return f"""<!DOCTYPE html><html><head><title>Comparison Report</title>
<link href="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.0/css/bootstrap.min.css" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.0/js/bootstrap.bundle.min.js"></script>
<style>
html {{ scroll-behavior: smooth; }}
.status-highlight {{ background:#fdecea !important; color:#d9534f; font-weight:bold; }}
.modal-xl {{ max-width: 95% !important; }}
</style></head><body class="p-3">

<h1>Comparison Report</h1>
<div class="mb-3">
  <button class="btn btn-sm btn-primary" onclick="filterAllRecords('all')">Show All</button>
  <button class="btn btn-sm btn-danger" onclick="filterAllRecords('changed')">Show Changed Only</button>
  <button class="btn btn-sm btn-secondary" onclick="filterAllRecords('unchanged')">Show Unchanged Only</button>
</div>

{summary_html}
<hr>{all_sections_html}
<script>
function filterDetailRows(recordId, filterType) {{
  let selector = recordId ? `#${{recordId}} table tbody tr` : 'div[id^="record-"] table tbody tr';
  document.querySelectorAll(selector).forEach(tr => {{
    const status = tr.getAttribute('data-status');
    if (filterType === 'changed') {{
      tr.style.display = status !== 'unchanged' ? '' : 'none';
    }} else if (filterType === 'unchanged') {{
      tr.style.display = status === 'unchanged' ? '' : 'none';
    }} else {{
      tr.style.display = '';
    }}
  }});
}}

function filterAllRecords(filterType) {{
  document.querySelectorAll('div[id^="record-"]').forEach(div => {{
    let changedCount = div.querySelectorAll('tr[data-status]:not([data-status="unchanged"])').length;
    if (filterType === 'changed') {{
      div.style.display = changedCount > 0 ? '' : 'none';
    }} else if (filterType === 'unchanged') {{
      div.style.display = changedCount === 0 ? '' : 'none';
    }} else {{
      div.style.display = '';
    }}
  }});
  document.querySelectorAll('#summary-table tbody tr').forEach(tr => {{
    if (tr.querySelector('td[colspan]')) {{
      tr.style.display = '';
      return;
    }}
    const status = tr.classList.contains('changed') ? 'changed' : 'unchanged';
    if (filterType === 'changed') {{
      tr.style.display = status === 'changed' ? '' : 'none';
    }} else if (filterType === 'unchanged') {{
      tr.style.display = status === 'unchanged' ? '' : 'none';
    }} else {{
      tr.style.display = '';
    }}
  }});
}}

function openModal(id) {{
  new bootstrap.Modal(document.getElementById(id)).show();
}}
</script></body></html>"""

def generate_summary_html(summary_data):
    table_records = defaultdict(list)
    for table_name, record_name, diff_count in summary_data:
        record_name = clean_text(record_name)
        table_records[table_name].append((record_name, diff_count))

    summary_rows = ""
    for table_name, records in table_records.items():
        summary_rows += f"""<tr><td colspan="4" class="table-primary"><strong>{table_name}</strong></td></tr>"""
        for record_name, diff_count in records:
            status_class = "changed" if diff_count > 0 else "unchanged"
            color_class = "text-danger fw-bold" if diff_count > 0 else "text-success"
            jump_link = f"#record-{record_name.replace(' ', '_').replace('.', '_')}"
            summary_rows += f"""
<tr class="{status_class}">
  <td style="white-space: nowrap;">{record_name}</td>
  <td class="{color_class}" style="text-align:center;">{diff_count}</td>
  <td class="text-center">{status_class.capitalize()}</td>
  <td class="text-center"><a href="{jump_link}" class="btn btn-sm btn-link">View</a></td>
</tr>"""
    return f"""
<h2>Summary by Table and Record</h2>
<table id="summary-table" class="table table-sm table-striped table-hover table-bordered w-auto align-middle">
<thead><tr><th>Record</th><th>Diffs</th><th>Status</th><th>Link</th></tr></thead><tbody>{summary_rows}</tbody></table>"""


def generate_detail_table(data1, data2, record_name):
    record_name = clean_text(record_name)
    all_keys = sorted(set(data1.keys()) | set(data2.keys()))
    record_id = record_name.replace(' ', '_').replace('.', '_')
    detail_rows = ""
    diff_count = 0
    for key in all_keys:
        val1, val2 = data1.get(key, ""), data2.get(key, "")
        status = "Unchanged"
        if val1 != val2:
            status = "Changed"
        elif val1 and not val2:
            status = "Removed"
        elif val2 and not val1:
            status = "Added"
        status_class = "status-highlight" if status != "Unchanged" else ""
        row_html = ""

        if "script" in key.lower() and val1 != val2:
            diff_html = generate_side_by_side_diff_html(val1, val2)
            popup_id = f"{record_id}_{key}"
            row_html = f"""
<tr data-status="{status.lower()}"><td>{key}</td><td colspan="2">
<button class="btn btn-sm btn-primary" onclick="openModal('{popup_id}')">View Diff</button>
<div class="modal fade" id="{popup_id}" tabindex="-1"><div class="modal-dialog modal-xl"><div class="modal-content"><div class="modal-body">{diff_html}</div></div></div></div></td><td class="{status_class}">{status}</td></tr>"""
        else:
            row_html = f"""
<tr data-status="{status.lower()}"><td>{key}</td><td>{val1}</td><td>{val2}</td><td class="{status_class}">{status}</td></tr>"""
        detail_rows += row_html
        if status != "Unchanged":
            diff_count += 1

    return diff_count, f"""
<div id="record-{record_id}" class="mb-4"><h3>{record_name}</h3>
<button class="btn btn-sm btn-primary" onclick="filterDetailRows('record-{record_id}', 'all')">All</button>
<button class="btn btn-sm btn-danger" onclick="filterDetailRows('record-{record_id}', 'changed')">Changed</button>
<button class="btn btn-sm btn-secondary" onclick="filterDetailRows('record-{record_id}', 'unchanged')">Unchanged</button>
<table class="table table-bordered table-sm"><thead><tr><th>Field</th><th>Instance1</th><th>Instance2</th><th>Status</th></tr></thead><tbody>{detail_rows}</tbody></table></div>"""

# ==================== Main ====================

def main():
    summary_data = []
    sections_html = []
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for table in TABLES:
        print(f"[INFO] Processing table: {table}")
        records = get_records(INSTANCE1['host'], INSTANCE1['user'], INSTANCE1['pass'], table, QUERY)
        for record in records:
            raw_name = record.get('name') or record.get('short_description') or record['sys_id']
            record_name = clean_text(raw_name)
            sys_id = record['sys_id']

            data1 = extract_all_tags(fetch_xml(INSTANCE1['host'], table, sys_id, INSTANCE1['user'], INSTANCE1['pass']))
            data2 = extract_all_tags(fetch_xml(INSTANCE2['host'], table, sys_id, INSTANCE2['user'], INSTANCE2['pass']))

            diff_count, detail_html = generate_detail_table(data1, data2, record_name)
            summary_data.append((table, record_name, diff_count))
            sections_html.append(detail_html)

    summary_html = generate_summary_html(summary_data)
    report_html = wrap_html_report("\n".join(sections_html), summary_html)

    output_path = os.path.join(OUTPUT_DIR, "comparison_report.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report_html)
    print(f"[✅] Report saved to {output_path}")

if __name__ == "__main__":
    main()
