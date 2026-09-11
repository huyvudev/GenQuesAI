import sys, json
sys.path.insert(0, "_rasoat_2llm_deploy")
from rasoat_2llm import lay_du_lieu_nguon, _prompt_user, LLMClient, _load_env, _SYS
from neo4j import GraphDatabase

env = _load_env("_rasoat_2llm_deploy/rasoat_2llm.env")
driver = GraphDatabase.driver(env["NEO4J_URI"], auth=(env["NEO4J_USER"], env["NEO4J_PASSWORD"]))
with driver.session() as neo:
    data = lay_du_lieu_nguon(neo, "155962")
src, targets = data
print("so targets:", len(targets))
user_prompt = _prompt_user(src, targets)
print("do dai prompt (ky tu):", len(user_prompt))
max_tok = max(1500, 500 + 200 * len(targets))
print("max_tok tinh duoc:", max_tok)

llm_gm = LLMClient("gemini", env.get("GEMINI_MODEL", "gemini-2.5-flash"), env["GEMINI_API_KEY"],
                   "https://generativelanguage.googleapis.com/v1beta/openai/",
                   extra={"extra_body": {"google": {"thinking_config": {"thinking_budget": 0}}}})
r = llm_gm._create(model=llm_gm.model, temperature=0, max_tokens=max_tok,
                   response_format={"type": "json_object"},
                   messages=[{"role": "system", "content": _SYS}, {"role": "user", "content": user_prompt}])
content = r.choices[0].message.content
print("finish_reason:", r.choices[0].finish_reason)
print("usage:", r.usage)
print("do dai content tra ve:", len(content) if content else 0)
print("--- 300 ky tu cuoi ---")
print(content[-300:] if content else None)
