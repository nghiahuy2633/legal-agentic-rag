"""Nhóm hỏi hiện trạng theo thứ tự bảng nghĩa vụ."""
GROUP_QUESTIONS = {
    "minh_bach": "Doanh nghiệp đã thực hiện thông báo, gắn nhãn và minh bạch nội dung AI như thế nào?",
    "phan_loai_thong_bao": "Doanh nghiệp đã phân loại rủi ro, thông báo và cập nhật thông tin hệ thống AI như thế nào?",
    "su_co": "Doanh nghiệp đã chuẩn bị gì để xử lý sự cố nghiêm trọng: quy trình khắc phục, tạm dừng, báo cáo cơ quan nhà nước, lưu nhật ký?",
    "danh_gia_phu_hop": "Doanh nghiệp đã chuẩn bị hồ sơ và thực hiện đánh giá sự phù hợp như thế nào?",
    "quan_ly_rui_ro_cao": "Doanh nghiệp đã quản lý rủi ro, dữ liệu, tài liệu kỹ thuật, giám sát và lưu nhật ký của hệ thống rủi ro cao như thế nào?",
    "nuoc_ngoai": "Nhà cung cấp nước ngoài đã bố trí đại diện và đầu mối liên hệ tại Việt Nam như thế nào?",
    "khu_vuc_cong": "Cơ quan đã rà soát điều kiện sử dụng, quản lý và giám sát hệ thống AI trong khu vực công như thế nào?",
    "chuyen_tiep": "Doanh nghiệp đã rà soát thời điểm đưa hệ thống vào sử dụng và chuẩn bị đáp ứng yêu cầu chuyển tiếp như thế nào?",
}


def status_groups(items):
    groups = {}
    for item in items:
        row = item["row"]
        if row.get("kind", "nghia_vu") == "nghia_vu" and row.get("group"):
            groups.setdefault(row["group"], []).append(item)
    return groups


def describe_groups(items):
    result = []
    for group, entries in status_groups(items).items():
        obligations = [{"id": i["row"]["id"], "obligation": i["row"]["obligation"]} for i in entries]
        question = GROUP_QUESTIONS.get(group, "Doanh nghiệp đã thực hiện các nghĩa vụ sau như thế nào?")
        question += "\n" + "\n".join(f"- {o['id']}: {o['obligation']}" for o in obligations)
        result.append(dict(group=group, question=question, obligations=obligations))
    return result


def next_group(items, answers):
    groups = describe_groups(items)
    progress = dict(answered=sum(g["group"] in answers for g in groups), total=len(groups))
    return {**next((g for g in groups if g["group"] not in answers),
                   dict(group=None, question=None, obligations=[])), "progress": progress}
