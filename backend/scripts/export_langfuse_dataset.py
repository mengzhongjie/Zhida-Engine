"""将 RAG 黄金评测集导出为可导入 Langfuse Dataset 的 CSV。

默认输入为 tests/fixtures/rag_golden_cases.jsonl，输出为同目录下的
langfuse_rag_golden_dataset.csv。Langfuse 的 CSV 上传器需要在界面中映射列；
它会自动识别名称含 Input、Expected 和 Metadata 的列，因此使用这三个表头。
"""

import argparse
import csv
import json
from pathlib import Path


DEFAULT_SOURCE = Path("tests/fixtures/rag_golden_cases.jsonl")
DEFAULT_OUTPUT = Path("tests/fixtures/langfuse_rag_golden_dataset.csv")


def load_cases(source: Path) -> list[dict]:
    cases: list[dict] = []
    with source.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            try:
                case = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"第 {line_number} 行不是有效 JSON") from exc
            if not isinstance(case.get("id"), str) or not isinstance(case.get("question"), str):
                raise ValueError(f"第 {line_number} 行必须包含 id 和 question")
            cases.append(case)
    return cases


def export(source: Path, output: Path) -> int:
    cases = load_cases(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=("Input", "Expected Output", "Metadata"))
        writer.writeheader()
        for case in cases:
            metadata = {
                "case_id": case["id"],
                "category": case.get("category"),
                "expected_document_ids": case.get("expected_document_ids", []),
                "required_facts": case.get("required_facts", []),
                "expected_behavior": case.get("expected_behavior"),
            }
            writer.writerow({
                "Input": case["question"],
                "Expected Output": case.get("expected_answer", ""),
                "Metadata": json.dumps(metadata, ensure_ascii=False),
            })
    return len(cases)


def main() -> None:
    parser = argparse.ArgumentParser(description="导出 Langfuse Dataset CSV")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    count = export(args.source, args.output)
    print(f"已导出 {count} 条：{args.output}")


if __name__ == "__main__":
    main()
