# Bot8 sales report audit — 2026-09-24

## Scope and evidence

- User asked for up to five genuine sale posts in each of 12 distinct groups of Khao Fang Nichapa and Preaw Buchakorn, with likes + comments + shares strictly greater than 100, no date filter, post link, screenshot, and at least 60 seconds between groups.
- First feed pass: 60 scrolls in every group, 16 candidates. Targeted second pass: search `พิกัด` and `สั่งซื้อ` in the 11 groups still short, up to 25 scrolls/query. Search start gaps were at least 116 seconds; the script also sleeps 60 seconds after finishing one group before starting the next.
- Final report: `data/reports/bot8-sales-20260924-150749/report.html` and `report.json`. It has 17 retained posts in 12 groups; all retained posts have a Facebook group URL, an existing PNG, and a numeric engagement sum >100. No duplicate URLs. Original pre-audit report is backed up as `report-before-audit.json/html`; excluded post records remain under `audit_rejected`, and their evidence images were not deleted.

## Why-Why: false sale candidates

1. Symptom: automated report included five posts that were a request for advice, a future promise to share product details, a personal purchase, or a general product deal without a purchase route.
2. Mechanism: the old sale matcher accepted generic `พิกัด`, `กดสั่ง`, `สั่งซื้อ`, and `ส่งฟรี` without distinguishing a seller's offer from a customer's question or purchase story. Screenshot inspection confirmed the mismatch (for example, asking which toothpaste to use and a photo of an already-purchased weight).
3. Root cause: a keyword hit was treated as positive evidence of an offer; it did not require a current shop link or clear purchase direction in the post. This is proved by the five captions and screenshots retained in the pre-audit report.
4. Fix: restrict `พิกัด` to concrete purchase-location phrases, stop treating `ส่งฟรี` alone as enough, exclude the observed request/past-purchase wording, and recheck the completed report. The five rejected rows are preserved in the JSON audit trail.
5. Verification: 4 negative and 3 positive caption regression checks passed; syntax checks passed; final JSON contains 12 groups, 17 retained posts, no score ≤100, no missing URL/PNG, and no duplicate URL. Several original and newly-found screenshots were opened visually. This does not prove there are no further qualifying posts deeper in Facebook search results.

## Final per-group counts

| Group | Confirmed posts |
|---|---:|
| ช้อปขั้นเทพ | 0 |
| รีวิวของดีประจำวัน | 0 |
| รีวิวครอบจักรวาล | 3 |
| แชร์ตรงปกมาก shopee / lazada | 1 |
| แต่งห้อง แต่งบ้าน แต่งเห๊อะ ขายทุกสิ่ง รีวิวทุกอย่าง | 5 |
| แต่งห้องนอนสไตล์มินิมอล | 0 |
| แชร์ทริคงานบ้าน | 1 |
| งานบ้านก็ต้องมีงานบิวตี้ก็ต้องโดน | 0 |
| แม่บ้านชอบรีวิว | 2 |
| สกินแคร์กู้หน้า ของใช้กู้บ้าน | 2 |
| แม่บ้านชอบซื้อ | 2 |
| ตัวแม่รีวิว ผิวเป๊ะบ้านปัง | 1 |

Groups below five mean fewer qualifying posts were confirmed within the inspected feed/search results, not proof that no more exist anywhere in those groups. No filler posts were added.
