"""Exercise evidence/report plumbing with synthetic text, not live research."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/deep-research-agent/scripts"))
from research import ResearchTools


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="research-runs/offline-demo")
    args = parser.parse_args()
    tools = ResearchTools(args.output)
    run = tools.call("research_begin", {
        "question": "虚构示例：方法 A 与方法 B 的资料来源有什么区别？",
        "subquestions": [{"id": "Q1", "question": "演示材料描述了什么？"}],
        "mode": "quick"
    })["run_id"]
    text = "方法A只处理用户提供的文本，不进行联网检索。方法B在读取用户文本之外，还能够向公开网页发出检索请求。本段为虚构演示材料，不代表真实产品性能。"
    source = tools.call("research_source", {
        "run_id": run, "url": "urn:user-document:synthetic-demo",
        "title": "虚构演示材料：非真实研究证据", "text": text,
        "read_scope": "test_fixture", "provenance": {"provider": "offline-demo-script"}
    })["source_id"]
    ids = []
    for quote, claim in [
        ("方法A只处理用户提供的文本，不进行联网检索。", "在这份虚构示例中，方法 A 只使用用户文本。"),
        ("方法B在读取用户文本之外，还能够向公开网页发出检索请求。", "在这份虚构示例中，方法 B 还可以检索公开网页。")
    ]:
        evidence = tools.call("research_quote", {"run_id": run, "source_id": source, "quote": quote})["evidence_id"]
        cid = tools.call("research_claim", {"run_id": run, "question_id": "Q1", "text": claim,
            "evidence_ids": [evidence]})["claim_id"]
        tools.call("research_review", {"run_id": run, "claim_id": cid, "verdict": "supported",
            "reason": "演示脚本预置的判断，仅用于展示记录格式；本例没有真实模型审阅。",
            "supporting_evidence_ids": [evidence]})
        ids.append(cid)
    result = tools.call("research_publish", {"run_id": run, "claim_ids": ids,
        "limitations": ["完全离线，使用虚构文字和预置审阅；没有真实联网检索，也没有真实模型研究。"],
        "stop_reason": "offline_demonstration"})
    assert result["status"] == "demonstration"
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
