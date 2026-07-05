import sys
with open(sys.argv[1], 'rb') as f:
    data = f.read()
lit = 0
i = 0
while i < len(data) - 1:
    if data[i:i+2] == b'\\n':
        lit += 1
    i += 1
print(f'lit_n={lit} of {data.count(chr(10))} lines - CRLF: {data.count(b"\\r\\n")}')