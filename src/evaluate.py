"""Shared test questions and scoring for every search method."""

TESTS = {
    # --- English, law's own wording ---
    "probation period": [53, 54],
    "notice period for terminating a contract": [75, 76],
    "maternity leave": [151],
    "overtime pay": [107],
    "end of service award after resignation": [84, 85],
    "maximum working hours per day": [98],
    # --- English, everyday wording ---
    "can my boss fire me during my trial period": [53, 80],
    "how many days off do I get per year": [109],
    "can my employer move me to another city": [58],
    "my salary was not paid on time": [90, 94],
    "non-compete clause after leaving the job": [83],
    "how much sick leave pay do I get": [117],
    "can my employer deduct money from my salary": [91, 92, 93],
    "who pays for my iqama and work permit": [40],
    "how long do I have to file a labor claim after leaving": [234],
    "paid leave when a family member dies": [113],
    "leave to perform Hajj": [114],
    "employee absent from work without excuse for many days": [80],
    "does a non-Saudi worker need a fixed-term contract": [37],
    "minimum age to employ a child": [162],
    "employer did not respond to my resignation": [79, 74],
    "working hours during Ramadan": [98],
    "certificate of experience when I leave": [64],
    "paid leave for university exams": [115],
    # --- Citing an article number ---
    "what does Article 77 say": [77],
    "Article 109": [109],
    "text of article 52": [52],
    # --- Arabic questions, English law ---
    "ما هي مدة فترة التجربة": [53],
    "كم يوم إجازة سنوية يستحق العامل": [109],
    "مكافأة نهاية الخدمة عند الاستقالة": [84, 85],
    "إجازة الوضع للمرأة العاملة": [151],
    "شرط عدم المنافسة بعد انتهاء العقد": [83],
    "أجر ساعات العمل الإضافية": [107],
}


def run_tests(engine, k: int = 3) -> dict:
    hit1 = hitk = 0
    rr = 0.0
    misses = []
    for query, expected in TESTS.items():
        found = [d["article_number"] for _, d in engine.search(query, k=10)]
        rank = next((i + 1 for i, n in enumerate(found) if n in expected), None)
        hit1 += rank == 1
        hitk += rank is not None and rank <= k
        rr += 1 / rank if rank else 0
        if not rank or rank > k:
            misses.append(f"  {query!r}: expected {expected}, got {found[:k]}")

    n = len(TESTS)
    print(f"Hit@1: {hit1}/{n}   Hit@{k}: {hitk}/{n}   MRR: {rr / n:.3f}")
    if misses:
        print(f"Misses (not in top {k}):")
        print("\n".join(misses))
    return {"hit1": hit1, "hitk": hitk, "mrr": rr / n}