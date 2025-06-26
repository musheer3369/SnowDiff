import os
import requests
import xml.etree.ElementTree as ET
import jsbeautifier
import difflib

INSTANCE1 = "ricohcanadadev"
INSTANCE2 = "ricohcanadarna"
SYS_ID = "0c8a1ec63b5aea5079aac51864e45acd"
USER1 = "moe.mohammad@ricoh-usa.com"
PASS1 = "Password.1"
USER2 = "moe.mohammad@ricoh-usa.com"
PASS2 = "Password.1"
OUTPUT_DIR = "comparison_reports"
TABLE = "sys_ui_action"
QUERY = "sys_created_byLIKEricoh-usa.com"  # Encoded query for sys_created_by endswith @ricoh-usa.com

TABLES = ["sys_ui_action", "sys_ui_policy","sys_script","sys_script_client","sys_script_include"]  # list of tables to compare

# === SERVICENOW UTILS ===
def get_records(instance, user, password, table, query):
    url = f"https://{instance}.service-now.com/api/now/table/{table}"
    params = {
        "sysparm_query": query,
        "sysparm_fields": "sys_id,name,short_description",
        "sysparm_limit": "1000"
    }
    resp = requests.get(url, auth=(user, password), params=params)
    resp.raise_for_status()
    return [
        {"sys_id": r["sys_id"], "name": r.get("name",""), "short_description": r.get("short_description","")}
        for r in resp.json().get("result", [])
    ]

def fetch_xml(instance, table, sys_id, user, password):
    url = f"https://{instance}.service-now.com/{table}.do?XML&sys_id={sys_id}"
    resp = requests.get(url, auth=(user, password))
    resp.raise_for_status()
    return ET.fromstring(resp.content)

def extract_all_tags(root):
    record_node = list(root)[0]
    result = {}
    for child in record_node:
        text = child.text or ""
        if child.tag.lower().startswith('script'):
            opts = jsbeautifier.default_options()
            opts.indent_size = 2
            text = jsbeautifier.beautify(text, opts)
        result[child.tag] = text
    return result

# === DIFF UTILS ===
def diff_html(a, b):
    diff = difflib.HtmlDiff(wrapcolumn=80)
    table_html = diff.make_table(
        a.splitlines(),
        b.splitlines(),
        context=False,
        numlines=3
    ).replace('class="diff"', 'class="diff_table"')
    return table_html.replace(
        '<td class="diff_header" nowrap="nowrap">',
        '<td class="diff_header" style="display:none;" nowrap="nowrap">'
    )

def generate_html_report_table(data1, data2, record_name, inst1, inst2):
    all_keys = sorted(set(data1.keys()) | set(data2.keys()))
    diff_count = 0
    record_id = record_name.replace(' ', '_').replace('.', '_')
    rows_html = []
    for key in all_keys:
        val1 = data1.get(key) or ""
        val2 = data2.get(key) or ""
        status = "Unchanged"
        if val1 is None and val2 is not None:
            status = "Added"
        elif val1 is not None and val2 is None:
            status = "Removed"
        elif val1 != val2:
            status = "Changed"
        if status != "Unchanged":
            diff_count += 1
        color = "#e0ffe0" if status == "Added" else "#ffe0e0" if status in ("Removed","Changed") else "#ffffff"
        if key.lower().startswith('script') and status == "Changed":
            diff_table = diff_html(val1, val2)
            popup_id = f"{record_id}_{key}"
            row_html = f"""
<tr style='background-color:{color}'>
  <td>{key}</td>
  <td colspan='3'>
    <button class="btn btn-sm btn-primary" onclick="openModal('{popup_id}')">View Diff</button>
    <div class="modal fade" id="{popup_id}" tabindex="-1">
      <div class="modal-dialog modal-dialog-centered modal-xl">
        <div class="modal-content">
          <div class="modal-header"><h5 class="modal-title">Diff for {record_name} - {key}</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
          </div>
          <div class="modal-body p-2" style="max-height:70vh; overflow-y:auto;">{diff_table}</div>
        </div>
      </div>
    </div>
  </td>
</tr>"""
        else:
            if key.lower().startswith('script'):
                val1 = f"<pre><code>{val1}</code></pre>"
                val2 = f"<pre><code>{val2}</code></pre>"
            row_html = f"""
<tr style='background-color:{color}'>
  <td>{key}</td><td>{val1}</td><td>{val2}</td><td>{status}</td>
</tr>"""
        rows_html.append(row_html)
    return diff_count, f"""
<div id="record-{record_id}">
<h2>Comparison for record: {record_name}</h2>
<p><strong>Difference count:</strong> {diff_count}</p>
<table class="table table-bordered table-striped table-sm">
<thead><tr><th>Field</th><th>{inst1}</th><th>{inst2}</th><th>Status</th></tr></thead>
<tbody>{"".join(rows_html)}</tbody></table>
</div>"""

# === HTML WRAPPER ===
def wrap_html_report(all_sections_html, summary_by_table):
    summary_html = []
    for table_name, summary_list in summary_by_table.items():
        summary_rows = "".join(
            f"<tr><td><a href='#record-{name.replace(' ', '_').replace('.', '_')}'>{name}</a></td><td>{diff_count}</td></tr>"
            for name, diff_count in summary_list
        )
        summary_html.append(f"""
<h2>Summary of Changes: {table_name}</h2>
<table class="table table-bordered table-striped table-sm">
<thead><tr><th>Name/Description</th><th>Changes Count</th></tr></thead>
<tbody>{summary_rows}</tbody></table>""")

    return f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ServiceNow Comparison Report</title>
<link href="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.0/css/bootstrap.min.css" rel="stylesheet">
<style>
.diff_table {{ width:100%; border-collapse: collapse; font-size: 0.75rem; }}
.diff_table th, .diff_table td {{ border:1px solid #ccc; padding:4px; white-space: pre-wrap; word-break:break-word; }}
.diff_table .diff_add {{ background:#e0ffe0; }}
.diff_table .diff_sub {{ background:#ffe0e0; }}
.diff_table .diff_chg {{ background:#ffffcc; }}
</style>
</head><body class="bg-light p-3">

<div class="container-fluid">
<h1 class="my-3">Comparison Report</h1>
{"".join(summary_html)}
{"".join(all_sections_html)}
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.0/js/bootstrap.bundle.min.js"></script>
<script>
function openModal(id) {{
  new bootstrap.Modal(document.getElementById(id)).show();
}}
</script>
</body></html>"""

# === MAIN SCRIPT ===
def main():
    summary_by_table = {}
    all_sections_html = []
    for table in TABLES:
        print(f"Processing table '{table}'...")
        records = get_records(INSTANCE1, USER1, PASS1, table, QUERY)
        table_summary = []
        for i, record in enumerate(records, 1):
            sys_id = record["sys_id"]
            name = record.get("name","").strip() or record.get("short_description","").strip() or sys_id
            print(f" [{i}/{len(records)}] Processing '{name}'...")
            data1 = extract_all_tags(fetch_xml(INSTANCE1, table, sys_id, USER1, PASS1))
            data2 = extract_all_tags(fetch_xml(INSTANCE2, table, sys_id, USER2, PASS2))
            diff_count, table_html = generate_html_report_table(data1, data2, name, INSTANCE1, INSTANCE2)
            table_summary.append((name, diff_count))
            all_sections_html.append(table_html)
        summary_by_table[table] = table_summary

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_file = os.path.join(OUTPUT_DIR, "comparison_report.html")
    report_html = wrap_html_report(all_sections_html, summary_by_table)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(report_html)
    print(f"✅ Report saved: {output_file}")

if __name__ == "__main__":
    main()
