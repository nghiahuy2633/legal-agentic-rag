"""Đáp án bộ sản phẩm mẫu, dựng trực tiếp từ luật, độc lập với bảng nghĩa vụ.

Mỗi nghĩa vụ chuẩn (G) có: vai trò áp dụng, mức rủi ro, điều kiện (đọc từ luật), tập đơn vị căn cứ
ở mức Khoản hoặc Điểm. Hệ thống được tính là tìm thấy G khi một dòng nó chọn có căn cứ thuộc tập đó.
"""
L, N = "134-2025-QH15", "142-2026-ND-CP"
u = lambda doc, d, k=None, p=None: f"{doc}_dieu-{d}" + (f"_khoan-{k}" if k else "") + (f"_diem-{p}" if p else "")

P, D, V, U = "nha_cung_cap", "ben_trien_khai", "nha_phat_trien", "nguoi_su_dung"
ANY, TBC, CAO, THAP, TB = "any", "tb_cao", "cao", "thap", "tb"
t = lambda f: (lambda x: x.get(f) is True)
AV = {"am_thanh", "hinh_anh", "video"}

# id: (vai trò, mức, điều kiện, đơn vị, ghi chú, optional)
G = {
    "G01": ({P}, ANY, None, [u(L, 10, 1), u(N, 6, 1)], "Nhà cung cấp tự phân loại trước khi đưa vào sử dụng", False),
    "G02": ({P}, TBC, None, [u(N, 12, 1), u(N, 12, 2)] + [u(N, 12, 2, p) for p in "abcd"], "Lập hồ sơ phân loại", False),
    "G03": ({P, D}, TBC, None, [u(N, 12, 6)], "Lưu trữ hồ sơ phân loại", False),
    "G04": ({P}, TBC, None, [u(L, 10, 3), u(N, 14, 1)], "Thông báo kết quả phân loại qua Cổng", False),
    "G05": ({P}, ANY, t("interacts_with_humans"), [u(L, 11, 1)], "Người dùng nhận biết đang tương tác với AI", False),
    "G06": ({P}, ANY, lambda x: bool(AV & set(x.get("content_types") or [])), [u(L, 11, 2), u(N, 17, 1), u(N, 17, 2), u(N, 17, 3), u(N, 17, 4)], "Đánh dấu máy đọc âm thanh, hình ảnh, video", False),
    "G07": ({D}, ANY, lambda x: x.get("generates_content") and x.get("public_distribution") and x.get("content_may_mislead") is not False, [u(L, 11, 3), u(N, 18, 1)], "Thông báo nội dung AI cung cấp ra công cộng", False),
    "G08": ({D}, ANY, lambda x: x.get("simulates_real_person") and x.get("public_distribution"), [u(L, 11, 4), u(N, 18, 2)], "Nhãn nội dung mô phỏng người thật, sự kiện thật", False),
    "G09": ({P, D}, ANY, lambda x: x.get("interacts_with_humans") or x.get("generates_content"), [u(L, 11, 5)], "Duy trì thông tin minh bạch", False),
    "G10": ({P, D}, ANY, None, [u(N, 16, 1), u(N, 16, 2)] + [u(N, 16, 2, p) for p in "abc"] + [u(N, 16, 3)], "Minh bạch chung: thông tin mục đích, hạn chế, lưu trữ, giải trình", True),
    "G11": ({P}, ANY, t("uses_third_party_model"), [u(N, 16, 6)], "Thỏa thuận với bên cung cấp mô hình", False),
    "G12": ({P}, TB, None, [u(L, 15, 1, "b")], "Giải trình (rủi ro trung bình), nhà cung cấp", False),
    "G13": ({D}, TB, None, [u(L, 15, 1, "c")], "Giải trình (rủi ro trung bình), bên triển khai", False),
    "G14": ({P}, THAP, None, [u(L, 15, 2, "a")], "Giải trình (rủi ro thấp), nhà cung cấp", False),
    "G15": ({D}, THAP, None, [u(L, 15, 2, "b")], "Giải trình (rủi ro thấp), bên triển khai", False),
    "G16": ({P, D, V, U}, ANY, None, [u(L, 12, 1)], "Bảo đảm an toàn, phát hiện và khắc phục sự cố", False),
    "G17": ({V, P}, ANY, None, [u(L, 12, 2, "a")], "Khắc phục, tạm dừng, thu hồi và thông báo khi sự cố nghiêm trọng", False),
    "G18": ({D, U}, ANY, None, [u(L, 12, 2, "b"), u(N, 19, 2, "a")], "Ghi nhận, hạn chế hậu quả, thông báo nhà cung cấp khi sự cố", False),
    "G19": ({P, D}, ANY, None, [u(N, 19, 3)] + [u(N, 19, 3, p) for p in "abc"], "Báo cáo sơ bộ sự cố nghiêm trọng", False),
    "G20": ({P, D}, ANY, None, [u(N, 19, 4)], "Nhật ký sự cố, báo cáo chính thức 15 ngày", False),
    "G21": ({P}, ANY, None, [u(N, 11, 1)] + [u(N, 11, 1, p) for p in "abcd"], "Rà soát, phân loại lại khi phát sinh sự kiện", True),
    "G22": ({P, D}, ANY, None, [u(N, 11, 3), u(N, 11, 3, "a")], "Thông báo khi phân loại lại cao hơn", True),
    "G23": ({D}, ANY, t("modified_by_deployer"), [u(N, 6, 4), u(N, 11, 2)], "Phối hợp phân loại lại khi bên triển khai sửa đổi", False),
    "G24": ({D}, ANY, None, [u(L, 10, 2)], "Bảo đảm an toàn, nguyên vẹn hệ thống khi sử dụng", False),
    "G25": ({P}, CAO, lambda x: x.get("requires_conformity_certification") is not False, [u(L, 13, 2, "a"), u(N, 13, 2, "a"), u(L, 13, 1), u(N, 13, 1)], "Đánh giá sự phù hợp qua tổ chức (diện bắt buộc chứng nhận)", False),
    "G26": ({P}, CAO, lambda x: x.get("requires_conformity_certification") is not True, [u(L, 13, 2, "b"), u(N, 13, 2, "b"), u(L, 13, 1), u(N, 13, 1)], "Đánh giá sự phù hợp (tự đánh giá hoặc dịch vụ)", False),
    "G27": ({P}, CAO, None, [u(N, 13, 6), u(L, 13, 3)], "Duy trì sự phù hợp, công khai kết quả đánh giá", False),
    "G28": ({P}, CAO, None, [u(L, 14, 1, "a"), u(N, 15, 1)], "Quản lý rủi ro", False),
    "G29": ({P}, CAO, None, [u(L, 14, 1, "b"), u(N, 15, 2, "b")], "Quản trị dữ liệu", False),
    "G30": ({P}, CAO, None, [u(L, 14, 1, "c")], "Hồ sơ kỹ thuật, nhật ký hoạt động", False),
    "G31": ({P}, CAO, None, [u(L, 14, 1, "d"), u(N, 15, 2, "c")], "Thiết kế giám sát, can thiệp của con người", False),
    "G32": ({P}, CAO, None, [u(L, 14, 1, "e")], "Giải trình, thông tin cho người sử dụng (rủi ro cao)", False),
    "G33": ({P}, CAO, None, [u(L, 14, 1, "g")], "Phối hợp kiểm tra, khắc phục sự cố", False),
    "G34": ({P}, CAO, None, [u(N, 15, 3)], "Cung cấp thông tin cho bên triển khai", False),
    "G35": ({D}, CAO, None, [u(L, 14, 2, "a"), u(N, 15, 5, "a")], "Vận hành đúng mục đích, phạm vi", False),
    "G36": ({D}, CAO, None, [u(L, 14, 2, "b"), u(N, 15, 5, "c")], "An toàn, bảo mật dữ liệu, can thiệp của con người", False),
    "G37": ({D}, CAO, None, [u(N, 15, 4)], "Tổ chức quản lý rủi ro khi triển khai", False),
    "G38": ({D}, CAO, None, [u(N, 15, 6), u(N, 15, 5, "d")], "Hạn chế rủi ro, thông báo khi phát hiện nguy cơ nghiêm trọng", False),
    "G39": ({D}, CAO, None, [u(L, 14, 2, "c")], "Duy trì tuân thủ tiêu chuẩn, quy chuẩn kỹ thuật", False),
    "G40": ({D}, CAO, None, [u(L, 14, 2, "đ")], "Giải trình về vận hành (rủi ro cao), bên triển khai", False),
    "G41": ({D}, CAO, None, [u(L, 14, 2, "e"), u(N, 15, 5, "đ")], "Phối hợp với nhà cung cấp, cơ quan nhà nước", False),
    "G42": ({D}, CAO, None, [u(N, 15, 5, "b")], "Giám sát hoạt động để phát hiện sai lệch, sự cố", False),
    "G43": ({U}, CAO, None, [u(L, 14, 3)], "Người sử dụng tuân thủ quy trình vận hành", False),
    "G44": ({P}, CAO, t("is_foreign_provider"), [u(L, 14, 6)], "Nhà cung cấp nước ngoài: đầu mối, đại diện tại Việt Nam", False),
    "G45": ("public", ANY, None, [u(L, 27, 1), u(N, 20, 6)], "Khu vực công: công khai, minh bạch, Khung đạo đức", False),
    "G46": ("public_deployer", ANY, t("public_decision_use"), [u(L, 27, 2)], "Không thay thế thẩm quyền quyết định", False),
    "G47": ("public_deployer", ANY, lambda x: x.get("risk_level") == "cao" or x.get("public_decision_use"), [u(L, 27, 3), u(N, 20, 1), u(N, 20, 3), u(N, 20, 4)] + [u(N, 20, 1, p) for p in "ab"] + [u(N, 20, 3, p) for p in "abcd"], "Đánh giá tác động, báo cáo", False),
    "G48": ("public_deployer", ANY, lambda x: x.get("risk_level") == "cao" or x.get("public_decision_use"), [u(L, 27, 4), u(N, 20, 5)], "Công khai báo cáo đánh giá tác động", False),
    "G49": ({U}, TB, None, [u(L, 15, 1, "d")], "Người sử dụng tuân thủ thông báo, gắn nhãn (rủi ro trung bình)", False),
    "G50": ({P, D, V, U}, ANY, None, [u(L, 28, 3)], "Cung cấp hồ sơ kỹ thuật, nhật ký, dữ liệu khi thanh tra, kiểm tra", False),
    "G51": ({D}, ANY, lambda x: bool(AV & set(x.get("content_types") or [])) and x.get("public_distribution"), [u(N, 17, 5)], "Bên triển khai đánh dấu đầu ra khi dùng hệ thống mã nguồn mở hoặc miễn phí", True),
}
G51_NOTE = "Người soát ghi: cần dữ kiện mã nguồn mở hoặc miễn phí; tạm optional."
G46_48_NOTE = ("Người soát ghi: G46, G47, G48 chỉ áp cho bên triển khai (cơ quan hoặc đơn vị vận hành). "
               "Nhà cung cấp tư nhân phục vụ dịch vụ công thuộc Thông tư 05 Điều 1 khoản 2, không thuộc Luật 134 Điều 27.")
G19_NOTE = ("Người soát chốt: Nghị định 142 Điều 19 khoản 3 giao báo cáo sơ bộ cho 'nhà cung cấp hoặc bên triển khai', "
            "bên triển khai báo cáo khi không liên lạc được nhà cung cấp. Đọc là nhà cung cấp báo cáo, bên triển khai dự phòng. "
            "Nghĩa vụ sự cố của bên triển khai được chấm qua G18. Optional khi vai trò không có nhà cung cấp.")

# Mục 4: căn cứ chỉ dẫn chiếu sang chỗ khác. Hệ thống trích các căn cứ này thì tính trung tính:
# không vào recall, không làm giảm precision (cài như nghĩa vụ chuẩn optional, áp cho mọi sản phẩm).
NEUTRAL = {
    "N01": ([u(L, 15, 1, "a")], "Trung tính: Luật 134 Điều 15 khoản 1 điểm a dẫn chiếu Điều 11"),
    "N02": ([u(L, 14, 1, "đ")], "Trung tính: Luật 134 Điều 14 khoản 1 điểm đ dẫn chiếu Điều 11, 12"),
    "N03": ([u(L, 14, 2, "d")], "Trung tính: Luật 134 Điều 14 khoản 2 điểm d dẫn chiếu Điều 11, 12"),
    "N04": ([u(N, 18, 3)] + [u(N, 18, 3, p) for p in "abcdđ"], "Trung tính: Nghị định 142 Điều 18 khoản 3 (yêu cầu hình thức nhãn, áp theo nghĩa vụ gắn nhãn)"),
}
NEUTRAL_NOTE = "Người soát chốt: căn cứ chỉ dẫn chiếu, tính trung tính."

CAM = {"C1": u(L, 7, 1), "C2": u(L, 7, 2, "b"), "C3": u(L, 7, 2, "c"), "C4": u(L, 7, 2, "d"), "C5": u(L, 7, 3), "C6": u(L, 7, 4), "C7": u(L, 7, 5)}


def risk_ok(level, risk):
    if level == ANY:
        return True
    want = {TBC: {"cao", "trung_binh"}, CAO: {"cao"}, THAP: {"thap"}, TB: {"trung_binh"}}[level]
    return risk in want


def gold_items(facts, optional_override=None):
    """optional_override: {gid: ghi chú} do người dùng chốt cho riêng một sản phẩm."""
    optional_override = optional_override or {}
    roles = set(facts.get("roles") or [])
    out = []
    for gid, (gr, level, cond, units, note, optional) in G.items():
        if gr in ("public", "public_deployer"):
            if facts.get("is_public_sector") is not True:
                continue
            if gr == "public_deployer" and D not in roles:
                continue
        elif gr != {P, D, V, U} and not (gr & roles):
            continue
        if not risk_ok(level, facts.get("risk_level")):
            continue
        if cond is not None and not cond(facts):
            continue
        item = dict(gid=gid, note=note, units=units, optional=optional)
        if gid in ("G46", "G47", "G48"):
            item["decision"] = G46_48_NOTE
        if gid == "G51":
            item["decision"] = G51_NOTE
        if gid == "G19" and P not in roles:
            item.update(optional=True, decision=G19_NOTE)
        if gid in optional_override:
            item.update(optional=True, decision=optional_override[gid])
        out.append(item)
    for gid, (units, note) in NEUTRAL.items():
        out.append(dict(gid=gid, note=note, units=units, optional=True, neutral=True, decision=NEUTRAL_NOTE))
    return out
