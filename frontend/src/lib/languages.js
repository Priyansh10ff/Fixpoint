export const LANGUAGES = {
  python: {
    label: 'Python',
    monaco: 'python',
    runtime: 'python 3.12',
    file: 'main.py',
    command: 'python main.py',
    example: `def binary_search(arr, target):
    lo, hi = 0, len(arr)
    while lo <= hi:
        mid = (lo + hi) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1


nums = list(map(int, input().split()))
target = int(input())
print(binary_search(nums, target))
`,
    stdin: '2 5 8 12 16 23 38 56 72 91\n100\n',
  },
  javascript: {
    label: 'JavaScript',
    monaco: 'javascript',
    runtime: 'node 20',
    file: 'main.js',
    command: 'node main.js',
    example: `const lines = require('fs').readFileSync(0, 'utf8').trim().split('\\n')
const words = lines[0].split(' ')

function longest(list) {
  let best = list[0]
  for (let i = 1; i <= list.length; i++) {
    if (list[i].length > best.length) best = list[i]
  }
  return best
}

console.log(longest(words))
`,
    stdin: 'fixed point iteration converges\n',
  },
  cpp: {
    label: 'C++',
    monaco: 'cpp',
    runtime: 'g++ 14 · c++17',
    file: 'main.cpp',
    command: 'g++ main.cpp && ./a.out',
    example: `#include <iostream>
#include <vector>
using namespace std;

int main() {
    int n;
    cin >> n;
    vector<int> a(n);
    for (int i = 0; i < n; i++) cin >> a[i];

    int sum = 0;
    for (int i = 0; i <= n; i++) sum += a[i];
    cout << sum << endl;
}
`,
    stdin: '5\n1 2 3 4 5\n',
  },
  java: {
    label: 'Java',
    monaco: 'java',
    runtime: 'temurin 21',
    file: 'Main.java',
    command: 'javac Main.java && java Main',
    example: `import java.util.*;

public class Main {
    static int factorial(int n) {
        return n * factorial(n - 1);
    }

    public static void main(String[] args) {
        Scanner sc = new Scanner(System.in);
        int n = sc.nextInt();
        System.out.println(factorial(n));
    }
}
`,
    stdin: '5\n',
  },
}

export const LANGUAGE_IDS = Object.keys(LANGUAGES)

export function javaFileName(code) {
  const m = code.match(/public\s+(?:(?:final|abstract)\s+)*class\s+([A-Za-z_]\w*)/)
  return `${m ? m[1] : 'Main'}.java`
}

export function fileNameFor(language, code) {
  return language === 'java' ? javaFileName(code) : LANGUAGES[language].file
}
