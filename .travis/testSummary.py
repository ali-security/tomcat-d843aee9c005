#!/usr/bin/env python3

# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Prints the JUnit results of `ant test` to the build log. antTest.sh sends
# ant's own output to ant-test.log (Travis caps log size), so without this the
# log would carry no test counts. Reads the plain-formatter reports
# output/build/logs/TEST-<class>.<NIO|NIO2|APR>.txt and prints one line per
# suite, every failing test, every skipped test with its reason (the runner's
# message, completed from the test source: the @Ignore value or comment, or the
# Assume statement), and per-connector totals last.

import glob
import os
import re
import sys

LOG_DIR = sys.argv[1] if len(sys.argv) > 1 else "output/build/logs"
TEST_SRC = sys.argv[2] if len(sys.argv) > 2 else "test"

RE_FILE = re.compile(r"TEST-(.+)\.([A-Z0-9]+)\.txt$")
RE_COUNTS = re.compile(r"^Tests run: (\d+), Failures: (\d+), Errors: (\d+), Skipped: (\d+)")
RE_CASE = re.compile(r"^Testcase: (\S+)")
RE_SKIP = re.compile(r"^\s*SKIPPED(?:: ?(.*))?$")
RE_FAIL = re.compile(r"^\s*(FAILED|Caused an ERROR)")

_src_cache = {}


def read_src(path):
    if path not in _src_cache:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                _src_cache[path] = f.read().split("\n")
        except OSError:
            _src_cache[path] = None
    return _src_cache[path]


def class_file(cls):
    return os.path.join(TEST_SRC, cls.split("$")[0].replace(".", os.sep) + ".java")


_all_files = None


def all_test_files():
    global _all_files
    if _all_files is None:
        _all_files = sorted(glob.glob(os.path.join(TEST_SRC, "**", "*.java"), recursive=True))
    return _all_files


def statement_from(lines, i):
    out = []
    for j in range(i, min(i + 6, len(lines))):
        out.append(lines[j].strip())
        if ";" in lines[j]:
            break
    return " ".join(out)


def preceding_reason(lines, i):
    """@Ignore value and comments directly above line i."""
    parts = []
    j = i - 1
    while j >= 0 and i - j <= 20:
        s = lines[j].strip()
        if s == "" or s.startswith("@") or s.startswith("//") or s.startswith("/*") \
                or s.startswith("*") or s.endswith("*/"):
            parts.insert(0, s)
            j -= 1
            continue
        break
    ignore = None
    comments = []
    for p in parts:
        m = re.search(r"@Ignore\s*\(\s*(?:value\s*=\s*)?\"(.*)\"", p)
        if m:
            ignore = m.group(1)
        elif p.startswith("@Ignore"):
            ignore = ignore or ""
        elif p.startswith(("//", "/*", "*")) or p.endswith("*/"):
            c = p.lstrip("/*").rstrip("*/").strip()
            if c and not c.startswith("@"):
                comments.append(c)
    return ignore, " ".join(comments)


def method_assumes(lines, i):
    """Assume.* statements in the body of the method declared at line i."""
    depth = 0
    started = False
    found = []
    for j in range(i, len(lines)):
        line = lines[j]
        if re.search(r"\bAssume\.|\bassume(True|False|NotNull|That|NoException)\s*\(", line):
            found.append(statement_from(lines, j))
        depth += line.count("{") - line.count("}")
        if "{" in line:
            started = True
        if started and depth <= 0:
            break
    return found


def setup_assumes(lines):
    found = []
    for j, line in enumerate(lines):
        if re.search(r"\bAssume\.|\bassume(True|False|NotNull|That|NoException)\s*\(", line):
            found.append(statement_from(lines, j))
    return found


def source_reason(cls, method):
    base = re.sub(r"\[.*$", "", method)
    candidates = [class_file(cls)]
    lines = read_src(candidates[0])
    # class-level @Ignore
    if lines:
        for i, l in enumerate(lines):
            if re.match(r"^public\s+(abstract\s+)?(final\s+)?class\s", l.strip()):
                ign, com = preceding_reason(lines, i)
                if ign is not None:
                    return "class-level @Ignore" + (": " + ign if ign else "") + \
                           (" -- source comment: " + com if com else " (bare @Ignore, upstream gives no comment)")
                break
    files = [candidates[0]] + [f for f in all_test_files() if f != candidates[0]]
    pat = re.compile(r"\bvoid\s+" + re.escape(base) + r"\s*\(")
    for f in files:
        ls = read_src(f)
        if not ls:
            continue
        for i, l in enumerate(ls):
            if pat.search(l):
                ign, com = preceding_reason(ls, i)
                where = os.path.relpath(f, TEST_SRC)
                if ign is not None:
                    r = "method @Ignore" + (": " + ign if ign else "")
                    r += (" -- source comment: " + com) if com else \
                        (" (bare @Ignore, upstream gives no comment)" if not ign else "")
                    return r + " [" + where + "]"
                asm = method_assumes(ls, i)
                if asm:
                    return "assumption in test: " + " | ".join(asm[:3]) + " [" + where + "]"
                break
        else:
            continue
        break
    if lines:
        asm = setup_assumes(lines)
        if asm:
            return "assumption in class setup/helpers: " + " | ".join(asm[:3])
    return None


def parse(path):
    suite = {"tests": 0, "fail": 0, "err": 0, "skip": 0, "skipped": [], "failed": []}
    current = None
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            m = RE_COUNTS.match(line)
            if m and suite["tests"] == 0:
                suite["tests"], suite["fail"], suite["err"], suite["skip"] = map(int, m.groups())
                continue
            m = RE_CASE.match(line)
            if m:
                current = m.group(1)
                continue
            m = RE_SKIP.match(line)
            if m and current is not None:
                if not any(s[0] == current for s in suite["skipped"]):
                    suite["skipped"].append((current, (m.group(1) or "").strip()))
                continue
            m = RE_FAIL.match(line)
            if m and current is not None and current not in suite["failed"]:
                suite["failed"].append(current)
    return suite


def main():
    files = sorted(glob.glob(os.path.join(LOG_DIR, "TEST-*.txt")))
    totals = {}
    all_skips = []
    all_fails = []
    print("=" * 78)
    print("JUnit results from " + LOG_DIR + " (" + str(len(files)) + " report files)")
    print("=" * 78)
    for path in files:
        m = RE_FILE.search(os.path.basename(path))
        if not m:
            continue
        cls, conn = m.group(1), m.group(2)
        s = parse(path)
        t = totals.setdefault(conn, {"suites": 0, "tests": 0, "fail": 0, "err": 0, "skip": 0})
        t["suites"] += 1
        for k in ("tests", "fail", "err", "skip"):
            t[k] += s[k]
        print("SUITE [%s] %s: run=%d passed=%d failures=%d errors=%d skipped=%d" % (
            conn, cls, s["tests"], s["tests"] - s["fail"] - s["err"] - s["skip"],
            s["fail"], s["err"], s["skip"]))
        for name in s["failed"]:
            all_fails.append((conn, cls, name))
        listed = list(s["skipped"])
        if s["skip"] > len(listed):
            listed.append(("<%d more not itemised>" % (s["skip"] - len(listed)), ""))
        for name, msg in listed:
            src = source_reason(cls, name)
            reason = []
            if msg:
                reason.append("runner message: " + msg)
            if src:
                reason.append(src)
            if not reason:
                reason.append("no message from runner and no reason found in source")
            all_skips.append((conn, cls, name, "; ".join(reason)))
    print("")
    print("FAILED TESTS (%d):" % len(all_fails))
    for conn, cls, name in all_fails:
        print("  FAILED [%s] %s.%s" % (conn, cls, name))
    print("")
    print("ALL SKIPPED TESTS (%d), each with its reason:" % len(all_skips))
    for conn, cls, name, reason in all_skips:
        print("  SKIPPED [%s] %s.%s -- %s" % (conn, cls, name, reason))
    print("")
    if not totals:
        print("TOTAL [none]: no JUnit report files found in " + LOG_DIR)
    for conn in sorted(totals):
        t = totals[conn]
        print("TOTAL [%s]: suites=%d tests=%d passed=%d failures=%d errors=%d skipped=%d" % (
            conn, t["suites"], t["tests"], t["tests"] - t["fail"] - t["err"] - t["skip"],
            t["fail"], t["err"], t["skip"]))


if __name__ == "__main__":
    main()
