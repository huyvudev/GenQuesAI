"""Chuyen hoidap_tvpl_gold.json (thuvienphapluat.vn) sang dinh dang tuong thich
voi Chatbot-Law/chatbot/eval/run_qa_gen_eval.py (chi can question/answer, cac
truong con lai la optional/bo sung).
"""
import json

SRC = "hoidap_tvpl_gold.json"
OUT = "hoidap_tvpl_gold_for_eval.jsonl"

data = json.load(open(SRC, encoding="utf-8"))

with open(OUT, "w", encoding="utf-8") as f:
    for r in data:
        rec = {
            "question": r["question"],
            "answer": r["answer"],
            "type": "external_gold",
            "source_comp_ids": r["cited_documents"],
            "bien_the_ngon_ngu": [],
            "_gold_id": r["id"],
            "_category": r["category"],
            "_source_url": r["source_url"],
        }
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

print(f"da ghi {len(data)} cau vao {OUT}")
