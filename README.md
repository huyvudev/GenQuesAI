# GenQuesAI

Sinh bộ đề eval và chấm hệ RAG pháp luật Việt Nam từ cây văn bản QPPL — 8 nhóm câu hỏi
tự động, hộp trắng lẫn hộp đen. Thiết kế đầy đủ ở
[`giai-phap-sinh-cau-hoi-eval.md`](giai-phap-sinh-cau-hoi-eval.md), lộ trình hiện tại ở
[`framework/ROADMAP.md`](framework/ROADMAP.md).

Hai ranh giới cần biết trước khi đọc tiếp:

- **`framework/`** chạy được trên máy TRẮNG — không Neo4j, không Qdrant, không cần cài
  hệ RAG nào. Đường JSONL + tầng truy vấn + tầng chấm đều thuần stdlib.
- **`generator/`** (sinh bộ đề) và phần hộp-trắng của `evaluate/` (chấm hệ) cần Neo4j +
  Qdrant của một hệ RAG cụ thể — xem [`generator/README.md`](generator/README.md) để
  nạp corpus của bạn.

## Cài đặt

```bash
pip install -e .              # framework tự chứa (soi/xuat corpus từ file JSONL)
pip install -e ".[neo4j]"     # thêm nạp thẳng từ Neo4j + Qdrant
pip install -e ".[dev]"       # thêm pytest
```

Cài xong có lệnh `genquesai` (xem `[project.scripts]` trong `pyproject.toml`); không
cài thì dùng `python -m genquesai.cli` tương đương.

## Bốn việc

```bash
genquesai corpus soi out/corpus        # báo cáo năng lực corpus (đủ dữ liệu để sinh 8 nhóm chưa?)
genquesai gen --out out/eval_set.jsonl --paraphrase all --c4   # sinh bộ đề
genquesai run --adapter legal_rag --out out/ket_qua_eval.json  # chấm hệ được đo
genquesai report out/ket_qua_eval.json                          # in lại báo cáo, không chấm lại
```

Mỗi lệnh con nhận đúng cờ của module gốc — `genquesai <lệnh> --help`. CLI chỉ định
tuyến; logic thật nằm ở `framework/cli.py`, `generator/run_all.py`, `evaluate/score.py`
— xem README riêng của từng thư mục khi cần đào sâu:

| Việc | Chi tiết |
|---|---|
| Sinh bộ đề, 8 nhóm câu hỏi | [`generator/README.md`](generator/README.md) |
| Chấm hệ được đo, adapter hộp trắng/đen | [`evaluate/README.md`](evaluate/README.md) |
| Schema `Corpus` trung gian, 2 loader | [`framework/corpus-schema.md`](framework/corpus-schema.md) |
| Bộ golden, cách kiểm bộ sinh không lặng lẽ hỏng | [`tests/README.md`](tests/README.md) |
| C5 — người soát đáp án tự động sinh | `generator/run_c5.py`, phiếu tự chứa mở bằng double-click |

## Cấu hình

Chỉ cần khi dùng `generator/` hoặc phần hộp-trắng của `evaluate/` — trỏ tới repo chứa
hệ RAG cần nạp (`framework/` một mình không cần gì cả):

```bash
cp genquesai.example.toml genquesai.toml   # rồi sửa legal_rag_root cho đúng máy
```

`genquesai.toml` không commit (xem `.gitignore` — mỗi máy một bản). Biến môi trường
`LEGAL_RAG_ROOT` vẫn ghi đè được lên file, ưu tiên cao hơn — tiện cho CI hoặc thử một
đường dẫn khác không muốn sửa file. Thứ tự đầy đủ và mặc định khi không có gì: xem
`framework/config.py`.

`.env` của chính hệ RAG (Neo4j/Qdrant/API key) vẫn nằm ở repo đó, không phải ở đây —
xem `generator/common.py::nap_env()`.

## `genquesai/legal_rag/` — đọc/ghi DB độc lập (CDI)

Bản clone cơ chế **tích hợp văn bản liên tục** (CDI — hashing/validate/dedup/ledger/
resync/undo/pipeline/watch/status) từ repo Chatbot-Law, để `generator/` đọc corpus
qua Neo4j **mà không cần trỏ `legal_rag_root` sang repo đó** (khác với mục Cấu hình ở
trên — đó chỉ còn cần cho đường chấm hộp trắng `--adapter legal_rag`, thứ *đang được
đo* nên không tự chủ được). Chi tiết phạm vi clone/lý do đặt tên: xem
`genquesai/legal_rag/__init__.py`.

```bash
pip install -e ".[cdi]"                          # + ".[cdi-embed]" nếu cần `embed`/`cdi watch`
cd genquesai/legal_rag
cp .env.example .env                             # rồi điền NEO4J_PASSWORD/QDRANT_API_KEY
python -m genquesai.legal_rag cdi status          # tổng quan: hiệu lực + published + ledger + đối soát
```

`.env` không commit (gitignored) — mẫu ở `genquesai/legal_rag/.env.example`.

### DB online

Ngoài Neo4j/Qdrant local (docker compose), có sẵn **DB online trên VPS** —
`221.132.33.149` (domain `hrental.name.vn`) — giữ đúng bản dữ liệu **mới nhất** (đã
qua các đợt crawl/ingest sau này mà local có thể chưa có). Server này **chỉ còn DB**:
chatbot BE/FE đã gỡ (2026-08-21), Neo4j (`7687`) + Qdrant (`6333`/`6334`) mở thẳng ra
internet cho hệ ngoài kết nối — Neo4j cần mật khẩu, **Qdrant bắt buộc api-key** (trước
đây không có auth). Trỏ `genquesai/legal_rag/.env` vào đó:

```bash
NEO4J_URI=bolt://221.132.33.149:7687
QDRANT_URL=http://221.132.33.149:6333
QDRANT_API_KEY=...   # xin key/mật khẩu Neo4j riêng, không ghi trong repo
```

Trước khi đổi giữa local ↔ online, chạy `cdi status` để so `Norm`/ledger — đừng đồng
bộ ngược nếu local đang cũ hơn.
