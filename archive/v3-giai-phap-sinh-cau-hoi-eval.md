# Giải pháp v3: Sinh bộ câu hỏi eval — kiến trúc Ragas, ruột văn bản QPPL

> **Mục tiêu:** giữ bộ khung kiến trúc của Ragas (KnowledgeGraph → Scenario → Synthesizer → Sample) để không phải phát minh lại, nhưng thay hai tầng đầu bằng đồ thị pháp lý thật, và ràng buộc để **mọi câu hỏi + đáp án sinh ra đều truy được nguyên văn về văn bản quy phạm pháp luật gốc** — không có một chữ nào do LLM tự viết ra rồi được coi là sự thật.

> **Thay đổi so với v2:** tái cấu trúc theo kiến trúc Ragas; thêm Mục 3 "Hợp đồng grounding" — 4 bất biến định nghĩa *thế nào là 100% thuận văn bản*, kèm 5 cổng kiểm tự động thi hành chúng; chuyển reference answer từ "đoạn nội dung" sang **span nguyên văn có offset**; chọn metric không-LLM cho phần retrieval.

---

## 1 — Ragas: lấy gì, bỏ gì

Ragas dựng testset qua 4 tầng. Ta giữ nguyên tầng 3–4, thay tầng 1–2.

| Tầng Ragas | Ragas làm gì | Ta làm gì | Vì sao |
|---|---|---|---|
| **1. Dựng node** | `apply_transforms()` chạy `HeadlineSplitter`, `SummaryExtractor`, `NERExtractor`, `KeyphraseExtractor` — LLM đọc chunk và tự sinh metadata | **Thay hoàn toàn.** Nạp node từ Neo4j: `Norm`, `Component`, `Expression`, kèm số hiệu, số Điều/Khoản, mốc hiệu lực, `chunk_id` | Metadata pháp lý đã có sẵn và chính xác. Để LLM trích lại NER từ text luật là tự tạo ra một nguồn sai mới |
| **2. Dựng cạnh** | `JaccardSimilarityBuilder` / `CosineSimilarityBuilder` / `OverlapScoreBuilder` — cạnh = "hai chunk giống nhau" | **Thay hoàn toàn.** Cạnh = `REPLACES`, `AMENDS`, `GUIDED_BY` từ đồ thị thật | Cạnh tương đồng ngữ nghĩa **không phải quan hệ pháp lý**. Multi-hop dựng trên nó sẽ ra câu hỏi vô nghĩa: "hai điều luật trông giống nhau" không sinh được tình huống nào có thật |
| **3. Scenario** | `_generate_scenarios()` tổ hợp `(nodes, persona, query_length, query_style)` | **Giữ, kế thừa.** Node do Cypher chọn thay vì sampling theo similarity; giữ nguyên trục persona/length/style | Trục đa dạng hoá này tốt và trực giao với tính đúng — nó chỉ đổi *cách hỏi*, không đổi *sự thật* |
| **4. Sample** | `_generate_sample()` — LLM viết **cả** `user_input` **và** `reference` từ chunk | **Chẻ đôi.** `reference` sinh deterministic từ span văn bản; LLM **chỉ** được chạm vào `user_input` | ⬅ **Đây là chỗ Ragas mất grounding.** Chi tiết ở Mục 3 |

Giữ nguyên: `KnowledgeGraph` / `Node` / `NodeType` / `Relationship` (dùng làm cấu trúc dữ liệu), `Persona`, `SingleTurnSample`, `BaseScenario`, và toàn bộ tầng metric khi đánh giá.

Không dùng: `apply_transforms`, mọi `*Extractor` LLM, mọi `*SimilarityBuilder`, và ba synthesizer mặc định (`SingleHopSpecificQuerySynthesizer`, `MultiHopAbstractQuerySynthesizer`, `MultiHopSpecificQuerySynthesizer`) — thay bằng 8 synthesizer riêng ở Mục 4.

---

## 2 — Nạp đồ thị pháp lý vào cấu trúc Ragas

Bước này thuần deterministic, không LLM.

```python
from ragas.testset.graph import KnowledgeGraph, Node, NodeType, Relationship

kg = KnowledgeGraph()

# Mỗi Expression (một phiên bản nội dung của một Điều tại một khoảng thời gian) = 1 node
for row in neo4j.run(CYPHER_EXPRESSIONS):
    kg.nodes.append(Node(
        type=NodeType.CHUNK,
        properties={
            "page_content":  row["text"],          # nguyên văn, KHÔNG tóm tắt
            "chunk_ids":     row["chunk_ids"],     # id trong index đang phục vụ RAG
            "norm_id":       row["norm_id"],       # số hiệu văn bản
            "component_ref": row["dieu_khoan"],    # "Điều 12 khoản 3"
            "hieu_luc_tu":   row["valid_from"],
            "hieu_luc_den":  row["valid_to"],      # None = còn hiệu lực
            "co_quan":       row["issuer"],
        },
    ))

# Cạnh mang đúng ngữ nghĩa pháp lý
for r in neo4j.run(CYPHER_RELATIONS):        # REPLACES | AMENDS | GUIDED_BY
    kg.relationships.append(Relationship(
        source=node_of[r["src"]], target=node_of[r["dst"]],
        type=r["type"],
        properties={"effective_date": r["effective_date"], "scope": r["scope"]},
    ))
```

Hai điểm bắt buộc:

- **`page_content` phải là nguyên văn văn bản**, không phải summary. Toàn bộ cơ chế grounding ở Mục 3 dựa trên việc đối chiếu chuỗi ký tự với nguồn gốc — có một lần tóm tắt xen vào là mất khả năng đó.
- **`chunk_ids` phải lấy từ chính index đang phục vụ RAG**, không phải chunk lại. Đây là điều kiện để tính được `context_recall` (xem Mục 6).

---

## 3 — Hợp đồng grounding: "100% thuận văn bản QPPL" nghĩa là gì

Đây là phần trả lời trực tiếp yêu cầu. "Thuận văn bản" phải là điều kiện **kiểm được bằng máy**, không phải lời hứa. Ta định nghĩa bằng 4 bất biến, mỗi bất biến có một cổng thi hành.

### I1 — Đáp án không bao giờ do LLM viết

Mọi `reference` phải thuộc đúng một trong ba dạng:

| Dạng | Mô tả | Ví dụ |
|---|---|---|
| **`span`** | Trích **nguyên văn** một đoạn văn bản, kèm offset | `{"chunk_id": "c_88213", "start": 412, "end": 690, "text": "Tổ chức, cá nhân sản xuất…"}` |
| **`field`** | Giá trị deterministic từ trường metadata | `"15/2018/NĐ-CP"`, `"2018-02-02"` |
| **`composed`** | Ghép `span`/`field` vào **khuôn câu cố định**, không có chữ tự do | `"{norm_id} bị thay thế bởi {new_norm_id}, hiệu lực từ {date}."` |

Cấm tuyệt đối dạng thứ tư: LLM đọc chunk rồi viết đáp án bằng lời của nó — kể cả khi đáp án đó đúng. Lý do: một đáp án đúng nhưng không truy được về span thì không kiểm được bằng máy, và mở đường cho những đáp án sai không kiểm được.

> **Đây chính là chỗ khác Ragas.** `_generate_sample()` mặc định của Ragas sinh `reference` bằng LLM. Ta override để nó không bao giờ được gọi cho trường này.

### I2 — Đáp án phải tái dựng được từ đúng phần đã trích dẫn

Mỗi item mang `gold_spans: [{chunk_id, start, end}]`. Bất biến: **xoá hết mọi thứ ngoài các span đó thì đáp án vẫn suy ra được.** Nếu cần thêm thông tin ở chỗ khác mới trả lời được → span trích thiếu → sửa hoặc loại item.

### I3 — LLM chỉ được đổi cách diễn đạt câu hỏi

LLM nhận **duy nhất** chuỗi câu hỏi template, trả về **duy nhất** chuỗi câu hỏi mới. Không thấy đáp án, không thấy span, không có quyền ghi vào trường nào khác.

Tập thực thể được bảo toàn (trích bằng regex, không bằng LLM):

- số hiệu văn bản (`\d+/\d{4}/[A-ZĐ\-]+`)
- ngày tháng mọi định dạng
- tham chiếu Điều / Khoản / Điểm
- tên cơ quan ban hành
- mọi con số định lượng (tiền, thời hạn, tỷ lệ, số lượng)

Quy tắc: thực thể trong bản gốc **hoặc còn nguyên, hoặc nằm trong danh sách cố ý lược bỏ** (khi chuyển sang dạng `situation`, xem Mục 5). **Xuất hiện thực thể mới ⇒ loại thẳng.** Không sửa, không thử lại — câu bị loại là câu rẻ, câu sai lọt lưới là câu đắt.

### I4 — Câu hỏi phải *cần* đến ngữ cảnh mới trả lời được

Bất biến này Ragas không có, và thiếu nó thì bộ eval sẽ thổi phồng điểm retrieval.

- **Kiểm khả đáp:** entailment check — `gold_spans` có kéo theo `reference` không? Không ⇒ loại.
- **Kiểm cần thiết (ablation):** hỏi cùng câu đó nhưng **không đưa ngữ cảnh**. Nếu mô hình vẫn trả lời đúng bằng kiến thức sẵn có ⇒ câu này không đo retrieval ⇒ hạ xuống nhóm phụ hoặc loại.

Kiểm thứ hai đặc biệt quan trọng với luật VN: nhiều điều khoản phổ biến đã nằm sẵn trong tham số mô hình.

### Năm cổng kiểm — chạy tuần tự, ghi tỷ lệ sống sót

| Cổng | Kiểm gì | Công cụ | Trượt thì |
|---|---|---|---|
| **C1** | `span.text` có **tồn tại nguyên văn** trong nguồn tại đúng offset không | So chuỗi | Loại (lỗi pipeline, phải báo) |
| **C2** | Bảo toàn thực thể sau paraphrase (I3) | Regex | Loại câu paraphrase, giữ bản template |
| **C3** | `gold_spans` ⊨ `reference` (I4a) | NLI / judge | Loại |
| **C4** | Không trả lời được khi bỏ ngữ cảnh (I4b) | Chạy không ngữ cảnh | Hạ nhóm |
| **C5** | Review tay mẫu phân tầng 50–100 câu | Người | Chặn nhóm nếu < 95% |

Tỷ lệ sống sót qua từng cổng là số liệu vận hành, phải log lại: C1 rớt nhiều ⇒ lỗi mapping chunk; C2 rớt nhiều ⇒ prompt paraphrase quá lỏng; C4 rớt nhiều ⇒ đang chọn toàn điều khoản phổ thông, cần lấy sâu hơn.

**Trần chính xác của bộ eval (`eval_set_ceiling`) = kết quả cổng C5.** Mọi chỉ số ở Mục 6 phải đọc kèm con số này — nó chặn trên tất cả.

---

## 4 — Tám synthesizer, mỗi cái đo một cấu phần

Kế thừa base class của Ragas nhưng override cả hai method.

| Mã | Mẫu hình / Cypher | Kế thừa | Cấu phần đo được | `reference` | Số câu |
|---|---|---|---|---|---|
| **G1** | `A -[:REPLACES]-> B` | `SingleHop` | Router → truy vấn metadata | `field` | 50 |
| **G2** | 1 `Component`, nhiều `Expression` theo thời gian | `SingleHop` | Bộ lọc thời gian, chọn phiên bản | `span` | 80 |
| **G3** | `Con -[:GUIDED_BY]-> Mẹ`, `Mẹ` bị `REPLACES` | `MultiHop` | Suy luận nhiều bước trên đồ thị | `composed` | 60 |
| **G4** | `Expression` bị đóng bởi `Action` | `MultiHop` | Tổng hợp danh sách | `field[]` | 40 |
| **G5** | `TransitionRule` đã duyệt gắn `Norm` | `MultiHop` | Router + suy luận điều kiện | `composed` | 30 |
| **G6** | Hai `Norm` xung đột (định nghĩa chặt, Mục 4.1) | `MultiHop` | **Hành vi từ chối** | nhãn | 25 |
| **G7** | Điều còn hiệu lực, nội dung độc lập | `SingleHop` | Vector retrieval + synthesis | `span` | 90 |
| **G8** | *(sinh chủ đích, không có trong đồ thị)* | — | **Chống bịa** | nhãn | 25 |
| | | | | **Tổng** | **400** |

Quota cố định, **không** cân theo số cạnh trong đồ thị: 8.063 cạnh `REPLACES` phản ánh cấu trúc hệ thống văn bản, không phản ánh phân bố câu hỏi người dùng cũng không phản ánh độ khó. G2 được trọng số cao nhất vì câu hỏi "tại một thời điểm" là chỗ RAG gãy nhiều nhất. Khi có log truy vấn thật, thêm **G9 — từ log** và dịch dần trọng số về phân bố thật; đó mới là căn cứ hợp lệ để đổi tỷ trọng.

Khung một synthesizer:

```python
@dataclass
class LegalSingleHopSynthesizer(SingleHopQuerySynthesizer):
    name: str = "G2_temporal"

    async def _generate_scenarios(self, n, knowledge_graph, persona_list, callbacks):
        # Cypher chọn ca CÓ ANH EM GẦN (Mục 5.2), không lấy ca dễ
        cands = select_multi_version_components(knowledge_graph, prefer_ambiguous=True)
        return [LegalScenario(nodes=[c.node], as_of=c.date,
                              persona=p, style=s, length=l)
                for c, p, s, l in balanced_product(cands, persona_list, STYLES, LENGTHS, n)]

    async def _generate_sample(self, scenario, callbacks):
        span = extract_span(scenario.nodes[0], scenario.as_of)   # deterministic — I1
        q_tpl = TEMPLATES[self.name].format(**scenario.slots)    # deterministic — I1
        q = await paraphrase(q_tpl, scenario.persona) if scenario.form == "situation" else q_tpl
        assert_entities_preserved(q_tpl, q)                      # cổng C2 — I3
        return SingleTurnSample(
            user_input=q,
            reference=span.text,                                 # nguyên văn, không qua LLM
            reference_contexts=[c.text for c in span.chunks],
        )
```

Điểm cần nhìn kỹ: `reference` đến từ `extract_span()`, không đến từ `await llm(...)`. `paraphrase()` chỉ đứng trên đường của `user_input` và bị chặn ngay sau đó bởi `assert_entities_preserved`.

### 4.1 — G6 phải định nghĩa chặt

"Hai `Norm` khác cấp cùng điều chỉnh một vấn đề" là **quá lỏng** — nghị định hướng dẫn luật là quan hệ bình thường, không phải mâu thuẫn. Label tự động theo tiêu chí đó sẽ phạt hệ thống vì nó trả lời đúng.

Chỉ vào G6 khi thoả **cả ba**: (1) hai norm cùng còn hiệu lực tại thời điểm hỏi; (2) cùng điều chỉnh một hành vi/đối tượng cụ thể; (3) đưa ra **hệ quả pháp lý khác nhau** (mức, thời hạn, điều kiện) — không phải chỉ khác mức độ chi tiết.

Điều kiện (3) không tự động hoá đáng tin được ⇒ **G6 human-verified 100%**. 25 câu sạch hơn 200 câu nhiễu.

---

## 5 — Persona và hai dạng câu hỏi

### 5.1 — Persona

Giữ `Persona` của Ragas, thay bằng vai người dùng thật của hệ:

| Persona | Cách hỏi đặc trưng |
|---|---|
| Cán bộ pháp chế doanh nghiệp | Biết số hiệu, hỏi trực tiếp về hiệu lực và sửa đổi |
| Chủ hộ kinh doanh | Không biết số hiệu, mô tả tình huống bằng ngôn ngữ đời thường |
| Luật sư | Hỏi so sánh phiên bản, hỏi ca chuyển tiếp |
| Người dân | Câu ngắn, thiếu ngữ cảnh, dùng từ không chính xác |

Persona **chỉ tác động lên bề mặt câu hỏi**, không bao giờ chạm vào `reference` — đúng như phân tách ở I1/I3.

### 5.2 — `lookup` vs `situation`

Câu template có nguy cơ **rò rỉ từ khoá**: câu hỏi chứa đúng số hiệu ⇒ BM25 trúng chunk đích ngay ⇒ điểm retrieval đẹp giả tạo.

- **`lookup`** — người hỏi biết số hiệu ("Nghị định 15/2018/NĐ-CP bị thay thế bởi văn bản nào?"). Đo graph/metadata, **không** đo retrieval.
- **`situation`** — chỉ mô tả sự việc, cố ý lược bỏ số hiệu ("Doanh nghiệp tôi nhập khẩu thực phẩm chức năng thì nay công bố sản phẩm theo quy định nào?"). Đây mới đo retrieval thật, và là dạng bắt buộc phải qua `paraphrase()`.

Mục tiêu **40% `lookup` / 60% `situation`**; G2 và G7 mỗi nhóm ≥ 50% `situation`.

**Distractor có chủ đích:** khi chọn ca, ưu tiên ca có "anh em gần" — cùng số hiệu khác năm, cùng số Điều khác văn bản, văn bản sửa nhiều lần liên tiếp (chọn phiên bản giữa). Ghi vào `distractor_ids`. Không có bước này, bộ eval không phân biệt nổi retriever tốt và retriever tệ.

---

## 6 — Đánh giá: chọn metric theo dạng đáp án

Ragas có cả metric dùng LLM và không dùng LLM. Vì ta đã có **gold chunk chính xác**, phần lớn nên dùng loại không-LLM: rẻ, nhanh, và **không trôi giữa các lần chạy** — điều kiện để so delta khi tinh chỉnh retrieval có ý nghĩa.

| Nhóm | Dạng đáp án | Metric |
|---|---|---|
| G1, G5 | `field` | Exact-match sau chuẩn hoá số hiệu/ngày |
| G4 | `field[]` | Set-F1 (phạt cả thiếu lẫn thừa) |
| G3 | `composed` | Exact-match nhãn + judge phần lý do (**chấm 2 điểm tách rời**) |
| G2, G7 | `span` | `Faithfulness`, `ResponseRelevancy` + `FactualCorrectness` |
| Mọi nhóm có gold chunk | — | `NonLLMContextRecall`, `NonLLMContextPrecisionWithReference` |
| G6, G8 | nhãn | Tỷ lệ nhận diện đúng — **chỉ số riêng, không gộp vào accuracy** |

Thêm `NoiseSensitivity` cho các item có `distractor_ids` — nó đo đúng thứ ta cố tình dựng ra.

Báo cáo **tách theo nhóm và theo `question_form`**, kèm `eval_set_ceiling`. Một con số tổng duy nhất che mất chính thứ cần biết.

Phân tích lỗi phải phân biệt được ba nguyên nhân: gold chunk **không nằm trong top-k** (retriever thiếu) / **distractor lọt vào trên gold** (retriever nhầm) / **gold có mặt nhưng trả lời sai** (synthesis). Ba nguyên nhân ⇒ ba hành động sửa khác hẳn nhau; `gold_spans` và `distractor_ids` tồn tại chính là để tách chúng.

---

## 7 — Schema output

Một dòng JSONL / item. Freeze lại; mọi lần chạy đọc đúng file đã freeze.

```json
{
  "id": "G2-0137",
  "group": "G2",
  "question_form": "situation",
  "persona": "chu_ho_kinh_doanh",
  "user_input": "Hiện nay nhập khẩu thực phẩm chức năng thì công bố sản phẩm thế nào?",
  "question_template": "Nội dung {component_ref} của {norm_id} tại thời điểm {as_of} là gì?",
  "as_of_date": "2024-07-01",

  "reference": "Tổ chức, cá nhân sản xuất, kinh doanh thực phẩm phải đăng ký bản công bố…",
  "reference_type": "span",
  "gold_spans": [{"chunk_id": "c_88213", "start": 412, "end": 690}],
  "reference_contexts": ["…"],
  "gold_node_ids": ["Expression:41207"],
  "distractor_ids": ["c_71902"],

  "gates": {"C1": "pass", "C2": "pass", "C3": "pass", "C4": "pass", "C5": "not_sampled"},
  "grader": "faithfulness+non_llm_context_recall",
  "difficulty": "hard",
  "human_verified": false,

  "graph_snapshot": "2026-08-06T14:00Z",
  "index_version": "bge-m3_v3",
  "generator_version": "v3.0"
}
```

Bắt buộc có `graph_snapshot` + `index_version` + `generator_version`: đồ thị hoặc index đổi thì bộ eval stale và so sánh giữa các lần chạy mất ý nghĩa. Khi một trong ba đổi, sinh bộ mới và **giữ bộ cũ** để so hồi quy.

---

## 8 — Tiêu chí nghiệm thu

- [ ] `eval_set_ceiling ≥ 95%` (cổng C5), đo **riêng từng nhóm**;
- [ ] cổng C1 rớt **0 câu** — C1 rớt là lỗi pipeline mapping chunk, không phải lỗi dữ liệu, phải sửa chứ không phải loại câu;
- [ ] 100% item có `reference_type ∈ {span, field, composed}`; **0 item** có reference do LLM viết;
- [ ] 100% item có `gold_spans` không rỗng, mọi `chunk_id` tồn tại trong index hiện hành, mọi `span.text` khớp nguyên văn tại offset;
- [ ] 0 câu paraphrase vi phạm C2;
- [ ] đủ 400 câu theo quota Mục 4, lệch mỗi nhóm ≤ 10%;
- [ ] `situation` ≥ 55% toàn bộ, G2/G7 mỗi nhóm ≥ 50%;
- [ ] G6 và G8 human-verified 100%;
- [ ] file JSONL đã freeze, đủ 3 trường version, đã commit.

Chưa đặt ngưỡng điểm mục tiêu cho hệ RAG — **vòng đầu để lấy baseline**, đặt ngưỡng sau khi có số thật.

---

## 9 — Thứ tự triển khai

1. **Xác nhận `chunk_id` có ổn định qua re-index không.** Nếu id đổi mỗi lần re-index thì toàn bộ `gold_spans` mục ngay lần re-index đầu — phải khoá bằng một identifier bền hơn *trước khi* sinh bất cứ câu nào. Đây là rủi ro số một của cả thiết kế.
2. Xác nhận tên nhãn/quan hệ Neo4j thật (`Norm`, `Component`, `Expression`, `Action`, `TransitionRule`, `REPLACES`, `AMENDS`, `GUIDED_BY`) — lệch thì chỉ phải sửa Cypher, không ảnh hưởng kiến trúc.
3. Nạp đồ thị → `KnowledgeGraph` (Mục 2), không LLM.
4. Dựng **G1 trước** (đơn giản nhất, `reference_type = field`) chạy hết 5 cổng để hiệu chỉnh pipeline kiểm tra, rồi mới mở sang G2/G7.
5. Chạy C5 trên mẫu phân tầng → chốt `eval_set_ceiling` → freeze.

---

## Phụ lục — còn thiếu từ phía dự án

- **Nguyên tắc bất biến #7** được viện dẫn cho hành vi từ chối (G6) nhưng chưa trích nội dung — cần chép một dòng để tài liệu tự đứng được.
- Ngưỡng entailment cho cổng C3 và mô hình dùng để chạy C4 chưa chốt.
- Chưa rõ index hiện hành lưu offset ký tự của chunk trong văn bản gốc hay không — nếu không, `gold_spans` phải rút gọn về `chunk_id` và bất biến I2 yếu đi một bậc.
