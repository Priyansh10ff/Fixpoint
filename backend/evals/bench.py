"""fixpoint-bench: small stdin programs with one realistic bug each, across all four languages.

Written for this project (CP / coursework style). Each task has the buggy program, a reference fix
used only for validation, and input/expected-output cases. `prepare()` drops any task whose
reference does not pass or whose bug does not show up, so a typo here cannot inflate results.
"""

from __future__ import annotations

from evals.tasks import Case, Task


def _t(id_, language, category, code, reference, cases):
    return Task(
        id=f"bench/{id_}",
        dataset="bench",
        language=language,
        code=code.lstrip("\n"),
        reference=reference.lstrip("\n"),
        cases=[Case(i, e) for i, e in cases],
        category=category,
    )


PY_RANGE = """
n = int(input())
nums = list(map(int, input().split()))
total = 0
for i in range(1, n):
    total += nums[i]
print(total)
"""

PY_AVERAGE = """
nums = list(map(int, input().split()))
avg = sum(nums) // len(nums)
print(f"{avg:.2f}")
"""

PY_PALINDROME = """
s = input().strip()
cleaned = "".join(ch for ch in s if ch.isalnum())
print("YES" if cleaned == cleaned[::-1] else "NO")
"""

PY_FIB = """
from functools import lru_cache


@lru_cache(maxsize=None)
def fib(n):
    if n <= 1:
        return 1
    return fib(n - 1) + fib(n - 2)


print(fib(int(input())))
"""

PY_COUNTS = """
def count_words(words, counts={}):
    for w in words:
        counts[w] = counts.get(w, 0) + 1
    return counts


q = int(input())
for _ in range(q):
    counts = count_words(input().split())
    print(max(counts.values()))
"""

JS_SORT = """
const data = require('fs').readFileSync(0, 'utf8').trim().split(/\\s+/).map(Number)
const sorted = data.sort()
console.log(sorted.join(' '))
"""

JS_SUM = """
const lines = require('fs').readFileSync(0, 'utf8').trim().split('\\n')
const nums = lines[1].split(' ').map(Number)
let total = 0
for (let i = 0; i <= nums.length; i++) total += nums[i]
console.log(total)
"""

JS_CONCAT = """
const [a, b] = require('fs').readFileSync(0, 'utf8').trim().split(/\\s+/)
console.log(a + b)
"""

CPP_OVERFLOW = """
#include <iostream>
#include <vector>
using namespace std;

int main() {
    int n;
    cin >> n;
    int total = 0;
    for (int i = 0; i < n; i++) {
        int x;
        cin >> x;
        total += x;
    }
    cout << total << endl;
}
"""

CPP_MAX = """
#include <iostream>
#include <vector>
using namespace std;

int main() {
    int n;
    cin >> n;
    vector<int> a(n);
    for (int i = 0; i < n; i++) cin >> a[i];
    int best = 0;
    for (int i = 0; i < n; i++)
        if (a[i] > best) best = a[i];
    cout << best << endl;
}
"""

CPP_BOUNDS = """
#include <iostream>
#include <vector>
using namespace std;

int main() {
    int n;
    cin >> n;
    vector<int> a(n);
    for (int i = 0; i < n; i++) cin >> a[i];
    int pairs = 0;
    for (int i = 0; i < n; i++)
        if (a[i] == a[i + 1]) pairs++;
    cout << pairs << endl;
}
"""

JAVA_AVG = """
import java.util.*;

public class Main {
    public static void main(String[] args) {
        Scanner sc = new Scanner(System.in);
        int n = sc.nextInt();
        int sum = 0;
        for (int i = 0; i < n; i++) sum += sc.nextInt();
        double avg = sum / n;
        System.out.printf("%.2f%n", avg);
    }
}
"""

JAVA_EQUALS = """
import java.util.*;

public class Main {
    public static void main(String[] args) {
        Scanner sc = new Scanner(System.in);
        String a = sc.next();
        String b = sc.next();
        System.out.println(a == b ? "SAME" : "DIFFERENT");
    }
}
"""


def load() -> list[Task]:
    return [
        _t("py-skip-first", "python", "off-by-one", PY_RANGE, PY_RANGE.replace("range(1, n)", "range(n)"),
           [("3\n1 2 3", "6"), ("1\n5", "5"), ("4\n0 0 0 7", "7"), ("2\n-1 -1", "-2"), ("5\n1 1 1 1 1", "5"), ("3\n10 20 30", "60"), ("2\n100 -100", "0")]),
        _t("py-integer-division", "python", "integer division", PY_AVERAGE, PY_AVERAGE.replace("//", "/"),
           [("1 2", "1.50"), ("2 4", "3.00"), ("1 1 2", "1.33"), ("5", "5.00"), ("7 8", "7.50"), ("3 4", "3.50"), ("10 20 30", "20.00")]),
        _t("py-palindrome-case", "python", "string normalisation", PY_PALINDROME,
           PY_PALINDROME.replace("cleaned = \"\".join(ch for ch in s if ch.isalnum())",
                                 "cleaned = \"\".join(ch.lower() for ch in s if ch.isalnum())"),
           [("Racecar", "YES"), ("abba", "YES"), ("abc", "NO"), ("A man, a plan, a canal: Panama", "YES"),
            ("Noon", "YES"), ("xy", "NO"), ("Was it a car or a cat I saw", "YES"), ("Hello", "NO")]),
        _t("py-fib-base-case", "python", "recursion base case", PY_FIB,
           PY_FIB.replace("if n <= 1:\n        return 1", "if n <= 1:\n        return n"),
           [("0", "0"), ("1", "1"), ("2", "1"), ("10", "55"), ("30", "832040"), ("5", "5"), ("20", "6765")]),
        _t("py-mutable-default", "python", "mutable default argument", PY_COUNTS,
           PY_COUNTS.replace("def count_words(words, counts={}):\n",
                             "def count_words(words, counts=None):\n    counts = {} if counts is None else counts\n"),
           [("2\na b a\nc", "2\n1"), ("1\nx x x", "3"), ("3\na\na\na", "1\n1\n1"), ("2\np q\nq q", "1\n2"), ("2\nz\nz z", "1\n2")]),
        _t("js-sort-numbers", "javascript", "comparator", JS_SORT,
           JS_SORT.replace("data.sort()", "data.sort((a, b) => a - b)"),
           [("10 9 1", "1 9 10"), ("3 2 1", "1 2 3"), ("100 20 3", "3 20 100"), ("5", "5"), ("-1 -10 2", "-10 -1 2"), ("1000 200 30 4", "4 30 200 1000"), ("2 11", "2 11")]),
        _t("js-loop-bound", "javascript", "off-by-one", JS_SUM, JS_SUM.replace("i <= nums.length", "i < nums.length"),
           [("3\n1 2 3", "6"), ("1\n4", "4"), ("2\n-5 5", "0"), ("4\n10 20 30 40", "100"), ("2\n7 8", "15")]),
        _t("js-string-concat", "javascript", "type coercion", JS_CONCAT,
           JS_CONCAT.replace("console.log(a + b)", "console.log(Number(a) + Number(b))"),
           [("2 3", "5"), ("10 20", "30"), ("0 0", "0"), ("-4 9", "5"), ("100 1", "101")]),
        _t("cpp-int-overflow", "cpp", "integer overflow", CPP_OVERFLOW,
           CPP_OVERFLOW.replace("int total = 0;", "long long total = 0;"),
           [("3\n1 2 3", "6"), ("2\n2000000000 2000000000", "4000000000"), ("1\n-5", "-5"),
            ("3\n1500000000 1500000000 1500000000", "4500000000"), ("3\n2147483647 1 0", "2147483648"), ("2\n1000000000 1000000000", "2000000000")]),
        _t("cpp-max-init", "cpp", "wrong initial value", CPP_MAX, CPP_MAX.replace("int best = 0;", "int best = a[0];"),
           [("3\n1 5 2", "5"), ("3\n-3 -1 -2", "-1"), ("1\n-7", "-7"), ("4\n0 0 0 0", "0"), ("2\n-9 4", "4"), ("3\n-100 -50 -75", "-50"), ("2\n3 3", "3")]),
        _t("cpp-out-of-bounds", "cpp", "out-of-bounds read", CPP_BOUNDS,
           CPP_BOUNDS.replace("for (int i = 0; i < n; i++)\n        if (a[i] == a[i + 1])",
                              "for (int i = 0; i + 1 < n; i++)\n        if (a[i] == a[i + 1])"),
           [("4\n1 1 2 2", "2"), ("3\n5 5 5", "2"), ("1\n7", "0"), ("2\n1 2", "0"), ("5\n1 2 2 3 3", "2"), ("2\n4 4", "1")]),
        _t("java-integer-average", "java", "integer division", JAVA_AVG,
           JAVA_AVG.replace("double avg = sum / n;", "double avg = (double) sum / n;"),
           [("2\n1 2", "1.50"), ("3\n1 1 2", "1.33"), ("1\n4", "4.00"), ("2\n7 8", "7.50"), ("3\n1 2 4", "2.33")]),
        _t("java-string-equals", "java", "reference equality", JAVA_EQUALS,
           JAVA_EQUALS.replace("a == b", "a.equals(b)"),
           [("abc abc", "SAME"), ("abc abd", "DIFFERENT"), ("x x", "SAME"), ("hello world", "DIFFERENT"), ("Same same", "DIFFERENT"), ("loop loop", "SAME")]),
    ]  # fmt: skip
