"""
Find the triple-quote imbalance by tracking open/close state.
Account for single-line docstrings (two triple-quotes on one line).
"""
path = r"c:\Users\10User\Desktop\NLPFInalVersion\backend\app\services\hybrid_matcher.py"
with open(path, encoding="utf-8") as f:
    lines = f.readlines()

in_string = False
string_start = None
parity_shifts = []  # Track where state changes

for i, line in enumerate(lines, 1):
    j = 0
    stripped = line
    while j < len(stripped) - 2:
        if stripped[j:j+3] == '"""':
            if in_string:
                in_string = False
                parity_shifts.append((i, "CLOSE", string_start))
            else:
                in_string = True
                string_start = i
                parity_shifts.append((i, "OPEN", i))
            j += 3
        else:
            j += 1

if in_string:
    print(f"UNCLOSED triple-quote! Last opened at line {string_start}")
    # Find when this string was opened
    # Work backwards through parity_shifts to find the OPEN that was never closed
    print(f"\nLast 20 parity shifts:")
    for line_num, action, ref in parity_shifts[-20:]:
        print(f"  Line {line_num:5d}: {action} (ref: {ref})")
    
    # Now let's check: is there a missing CLOSE somewhere?
    # Print lines around the last OPEN
    start = max(0, string_start - 3)
    end = min(len(lines), string_start + 3)
    print(f"\nContext around last OPEN (line {string_start}):")
    for k in range(start, end):
        marker = ">>>" if k == string_start - 1 else "   "
        print(f"{marker} {k+1:4d}: {lines[k].rstrip()}")
else:
    print("All triple-quotes are properly paired.")

# Also check: does any regular (non-triple-quoted) string contain embedded triple quotes?
# Check for lines with a `#` comment containing `"""`
print("\n--- Lines with # comment containing triple-quotes ---")
for i, line in enumerate(lines, 1):
    hash_pos = -1
    # Naive: find first # that might be a comment
    in_sq = False
    in_dq = False
    for j, ch in enumerate(line):
        if ch == "'" and not in_dq:
            in_sq = not in_sq
        elif ch == '"' and not in_sq:
            in_dq = not in_dq
        elif ch == '#' and not in_sq and not in_dq:
            hash_pos = j
            break
    if hash_pos >= 0 and '"""' in line[hash_pos:]:
        print(f"  Line {i}: {line.rstrip()}")
