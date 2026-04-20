import re

with open('c:/projects/Bca_project/app.py', 'r', encoding='utf-8') as f:
    content = f.read()
    lines = content.split('\n')

# Fix chunk 1: slicing out the duplicates
new_lines = lines[:901]
new_lines.append('    conn.close()')
new_lines.append('    ')
new_lines.append('    flash(f"Exam submitted successfully! Your grade: {marks_percentage}% ({status})")')
new_lines.append("    return redirect(url_for('student_dashboard'))")
new_lines.append('')
new_lines.extend(lines[1102:])

new_content = '\n'.join(new_lines)

# Fix chunk 2: dictionaries for admin_alerts template compatibility with sqlite3.Row missing audio_path
new_content = new_content.replace(
    "alerts = conn.execute(query, params).fetchall()",
    "alerts = [dict(row) for row in conn.execute(query, params).fetchall()]"
)

with open('c:/projects/Bca_project/app.py', 'w', encoding='utf-8') as f:
    f.write(new_content)
print("Fix applied successfully to app.py")
