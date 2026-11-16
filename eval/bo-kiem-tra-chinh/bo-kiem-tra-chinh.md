# Bộ kiểm tra chính (30 câu)

Bản đọc, sinh từ `eval/bo-kiem-tra-chinh/questions.jsonl` và `eval/bo-kiem-tra-chinh/answers.jsonl`. Không dùng để chạy.

Trình chạy đánh giá đọc cố định `eval/questions.jsonl` và `eval/answers.jsonl`, tức bộ dev. Muốn sinh lại câu trả lời trên bộ này thì chép hai file của `eval/bo-kiem-tra-chinh/` vào `eval/` trong một worktree riêng, chạy xong không commit hai file đó. `eval/bo-kiem-tra-chinh/analyze.py` đọc thẳng từ `eval/bo-kiem-tra-chinh/`.

## t001 · pham_vi · tra_cuu · de

**Câu hỏi:** Ứng dụng của startup tôi cần có đặc điểm gì để được coi là hệ thống AI?  
*Người hỏi:* startup làm ứng dụng AI · *Mong đợi:* tra_loi

**Đáp án chuẩn:** Theo khoản 2 Điều 3 Luật Trí tuệ nhân tạo, ứng dụng cần là hệ thống dựa trên máy, được thiết kế để thực hiện các năng lực trí tuệ nhân tạo với các mức độ tự chủ khác nhau, có khả năng tự thích nghi sau khi được triển khai. Khoản 1 Điều 3 định nghĩa trí tuệ nhân tạo là việc thực hiện bằng điện tử các năng lực trí tuệ của con người, bao gồm học tập, suy luận, nhận thức, phán đoán và hiểu ngôn ngữ tự nhiên. Hệ thống căn cứ vào các mục tiêu được xác định rõ ràng hoặc được hình thành một cách ngầm định để suy luận từ dữ liệu đầu vào, tạo ra các đầu ra như dự đoán, nội dung, khuyến nghị hoặc quyết định có thể gây ảnh hưởng tới môi trường vật lý hoặc môi trường số.

**Ý bắt buộc:**
1. Ứng dụng cần là hệ thống dựa trên máy, được thiết kế để thực hiện các năng lực trí tuệ nhân tạo với các mức độ tự chủ khác nhau.
2. Trí tuệ nhân tạo là việc thực hiện bằng điện tử các năng lực trí tuệ của con người, bao gồm học tập, suy luận, nhận thức, phán đoán và hiểu ngôn ngữ tự nhiên.
3. Hệ thống cần có khả năng tự thích nghi sau khi được triển khai.
4. Hệ thống căn cứ vào mục tiêu được xác định rõ ràng hoặc hình thành ngầm định để suy luận từ dữ liệu đầu vào và tạo ra đầu ra có thể gây ảnh hưởng tới môi trường vật lý hoặc môi trường số.

**Căn cứ:** 134-2025-QH15_dieu-3_khoan-2, 134-2025-QH15_dieu-3_khoan-1

## t002 · pham_vi · xac_nhan · trung_binh

**Câu hỏi:** Công cụ của shop chỉ tính phí vận chuyển theo bảng giá cố định cũng được coi là hệ thống AI, đúng hay sai?  
*Người hỏi:* chủ shop bán hàng online · *Mong đợi:* tra_loi

**Đáp án chuẩn:** Sai. Theo khoản 2 Điều 3 Luật Trí tuệ nhân tạo, hệ thống trí tuệ nhân tạo được thiết kế để thực hiện các năng lực trí tuệ nhân tạo với các mức độ tự chủ khác nhau, có khả năng tự thích nghi sau khi triển khai và suy luận từ dữ liệu đầu vào để tạo ra đầu ra. Với mô tả chỉ tính phí vận chuyển theo bảng giá cố định, công cụ của shop không đáp ứng định nghĩa này.

**Ý bắt buộc:**
1. Nhận định là sai: công cụ chỉ tính phí vận chuyển theo bảng giá cố định không đáp ứng định nghĩa hệ thống trí tuệ nhân tạo tại khoản 2 Điều 3.

**Căn cứ:** 134-2025-QH15_dieu-3_khoan-2

## t003 · pham_vi · tinh_huong · kho

**Câu hỏi:** Cty tài chính mình có công cụ duyệt hồ sơ theo bộ quy tắc cố định, bên bán lại quảng cáo là AI, bên mình cần kiểm tra gì để biết có phải áp dụng luật AI ko?  
*Người hỏi:* ngân hàng, công ty tài chính · *Mong đợi:* tra_loi

**Đáp án chuẩn:** Không thể kết luận công cụ thuộc Luật Trí tuệ nhân tạo chỉ vì bên bán quảng cáo là AI; cần đối chiếu hoạt động thực tế với khoản 2 Điều 3, gồm thiết kế thực hiện năng lực trí tuệ nhân tạo, mức độ tự chủ, khả năng tự thích nghi sau triển khai và việc suy luận từ dữ liệu đầu vào theo mục tiêu để tạo đầu ra có thể ảnh hưởng tới môi trường vật lý hoặc môi trường số. Nên yêu cầu bên bán giải thích cơ chế xử lý, thành phần nào chỉ thực thi quy tắc cố định, thành phần nào là mô hình được huấn luyện từ dữ liệu để học, biểu diễn và suy luận; thông tin về mô hình cần được xem xét cùng định nghĩa toàn bộ hệ thống trước khi kết luận. Luật áp dụng với tổ chức tham gia hoạt động AI tại Việt Nam, và công ty là bên triển khai nếu sử dụng hệ thống AI thuộc phạm vi kiểm soát của mình trong hoạt động kinh doanh. Nếu xác định là hệ thống AI, nhà cung cấp có trách nhiệm tự phân loại rủi ro trước khi đưa vào sử dụng và chịu trách nhiệm về tính chính xác, trung thực của kết quả. Nếu công cụ duyệt hồ sơ cấp tín dụng, cần kiểm tra thêm mục tương ứng trong Danh mục rủi ro cao: hệ thống thực hiện chấm điểm tín dụng, đánh giá khả năng trả nợ và tự động quyết định cấp tín dụng hoặc giải ngân, đồng thời đáp ứng các điều kiện về quyết định phê duyệt hoặc từ chối cuối cùng, sử dụng trực tiếp quyết định mà không có phê duyệt độc lập của cán bộ tín dụng và giá trị khoản vay theo quy định của Ngân hàng Nhà nước.

**Ý bắt buộc:**
1. Quảng cáo là AI chưa đủ để kết luận áp dụng Luật; cần kiểm tra công cụ thực tế có đáp ứng định nghĩa hệ thống trí tuệ nhân tạo hay không.
2. Khi kiểm tra thành phần mô hình AI, cần đối chiếu đặc tính được huấn luyện từ dữ liệu để học, biểu diễn và suy luận các quy luật của dữ liệu.
3. Luật áp dụng đối với tổ chức Việt Nam và nước ngoài tham gia hoạt động trí tuệ nhân tạo tại Việt Nam.
4. Công ty là bên triển khai nếu sử dụng hệ thống AI thuộc phạm vi kiểm soát của mình trong hoạt động nghề nghiệp, thương mại hoặc cung cấp dịch vụ.
5. Nếu công cụ là hệ thống AI, nhà cung cấp có trách nhiệm tự phân loại rủi ro trước khi đưa vào sử dụng và chịu trách nhiệm về tính chính xác, trung thực của kết quả.
6. Nếu công cụ AI duyệt cấp tín dụng, cần đối chiếu đầy đủ điều kiện của mục hệ thống tự động quyết định cấp tín dụng trong Danh mục rủi ro cao.

**Căn cứ:** 134-2025-QH15_dieu-3_khoan-2, 142-2026-ND-CP_dieu-3_khoan-4, 134-2025-QH15_dieu-2, 134-2025-QH15_dieu-3_khoan-5, 142-2026-ND-CP_dieu-6_khoan-1, 33-2026-QD-TTg_linh-vuc-IV_stt-2

## t004 · vai_tro · thu_tuc · trung_binh

**Câu hỏi:** Phong kham thue AI doc phim va tu cau hinh nguong canh bao thi can doi chieu nhung thong tin cu the nao de xac dinh vai tro phap ly cua minh?  
*Người hỏi:* bệnh viện, phòng khám · *Mong đợi:* tra_loi

**Đáp án chuẩn:** Chỉ thông tin phòng khám thuê AI đọc phim và tự cấu hình ngưỡng cảnh báo chưa đủ để kết luận đầy đủ các vai trò pháp lý của phòng khám. Cần xác định hệ thống có thuộc phạm vi kiểm soát của phòng khám và được sử dụng trong hoạt động nghề nghiệp, thương mại hoặc cung cấp dịch vụ hay không để đối chiếu vai trò bên triển khai. Cần xác định ai đưa hệ thống ra thị trường hoặc đưa vào sử dụng dưới tên, thương hiệu hoặc nhãn hiệu của mình để nhận diện nhà cung cấp, kể cả khi hệ thống do bên thứ ba phát triển. Đối với việc chỉnh ngưỡng, cần kiểm tra thao tác thực tế có thuộc thiết kế, xây dựng, huấn luyện, kiểm thử hoặc tinh chỉnh toàn bộ hoặc một phần mô hình, thuật toán hoặc hệ thống AI hay không, đồng thời phòng khám có quyền kiểm soát trực tiếp phương pháp kỹ thuật, dữ liệu huấn luyện hoặc tham số mô hình hay không để đối chiếu vai trò nhà phát triển. Cũng cần xác định phòng khám có trực tiếp tương tác với hệ thống hoặc sử dụng kết quả đọc phim để đối chiếu vai trò người sử dụng.

**Ý bắt buộc:**
1. Cần đối chiếu phạm vi kiểm soát hệ thống và việc sử dụng trong hoạt động nghề nghiệp, thương mại hoặc cung cấp dịch vụ để xác định vai trò bên triển khai.
2. Cần xác định chủ thể đưa hệ thống ra thị trường hoặc đưa vào sử dụng dưới tên, thương hiệu hoặc nhãn hiệu của mình để nhận diện nhà cung cấp.
3. Cần đối chiếu thao tác cấu hình thực tế và quyền kiểm soát trực tiếp phương pháp kỹ thuật, dữ liệu huấn luyện hoặc tham số mô hình với định nghĩa nhà phát triển.
4. Cần xác định việc trực tiếp tương tác với hệ thống hoặc sử dụng kết quả đầu ra để đối chiếu vai trò người sử dụng.

**Căn cứ:** 134-2025-QH15_dieu-3_khoan-5, 134-2025-QH15_dieu-3_khoan-4, 134-2025-QH15_dieu-3_khoan-3, 134-2025-QH15_dieu-3_khoan-6

## t005 · vai_tro · tien_de_sai · trung_binh

**Câu hỏi:** Vì trường học thuê doanh nghiệp vận hành AI thì toàn bộ nghĩa vụ của bên triển khai tự động chuyển sang doanh nghiệp, trường cần ghi nhận việc chuyển giao đó như thế nào?  
*Người hỏi:* trường học · *Mong đợi:* tra_loi

**Đáp án chuẩn:** Không có căn cứ trong bốn văn bản để cho rằng thuê doanh nghiệp vận hành AI tự động chuyển toàn bộ nghĩa vụ của bên triển khai sang doanh nghiệp; trường vẫn là bên triển khai nếu sử dụng hệ thống thuộc phạm vi kiểm soát của mình để cung cấp dịch vụ. Nếu hệ thống có rủi ro cao, trường với tư cách bên triển khai vẫn phải thực hiện các trách nhiệm theo khoản 2 Điều 14 Luật Trí tuệ nhân tạo, gồm vận hành, giám sát, bảo đảm an toàn, bảo mật dữ liệu, khả năng can thiệp của con người, tuân thủ tiêu chuẩn và quy chuẩn kỹ thuật, minh bạch, xử lý sự cố, giải trình và phối hợp. Trong phạm vi áp dụng của Thông tư 05/2026/TT-BKHCN, hướng dẫn sử dụng Khung đạo đức yêu cầu phân định rõ trách nhiệm giữa các bên, bao gồm nhà thầu, thiết lập cơ chế giải trình, tiếp nhận phản ánh và phối hợp khắc phục vấn đề đạo đức. Bốn văn bản không quy định thủ tục hoặc mẫu ghi nhận việc chuyển giao toàn bộ nghĩa vụ do thuê vận hành, nên không có cơ sở hướng dẫn trường ghi nhận một sự chuyển giao tự động như tiền đề câu hỏi.

**Ý bắt buộc:**
1. Tiền đề sai: thuê doanh nghiệp vận hành không tự động chuyển toàn bộ nghĩa vụ; trường vẫn là bên triển khai nếu sử dụng hệ thống thuộc phạm vi kiểm soát của mình để cung cấp dịch vụ.
2. Nếu hệ thống có rủi ro cao và trường là bên triển khai, trường vẫn phải thực hiện các trách nhiệm vận hành, giám sát, an toàn, bảo mật dữ liệu, minh bạch, xử lý sự cố, giải trình và phối hợp theo luật.
3. Theo hướng dẫn sử dụng Khung đạo đức, trong phạm vi áp dụng của Thông tư, cần phân định rõ trách nhiệm của các bên, bao gồm nhà thầu, và có cơ chế phối hợp khắc phục vấn đề đạo đức.
4. Trong phạm vi bốn văn bản được kiểm tra, không có quy định về thủ tục hoặc mẫu ghi nhận việc chuyển giao toàn bộ nghĩa vụ của bên triển khai do thuê doanh nghiệp vận hành AI.

**Căn cứ:** 134-2025-QH15_dieu-3_khoan-5, 134-2025-QH15_dieu-14_khoan-2, 05-2026-TT-BKHCN_phu-luc-1_muc-2

## t006 · vai_tro · tra_cuu · de

**Câu hỏi:** Cơ quan nhà nước trực tiếp vận hành hệ thống AI có được coi là bên triển khai không?  
*Người hỏi:* cơ quan nhà nước · *Mong đợi:* tra_loi

**Đáp án chuẩn:** Có, khi cơ quan nhà nước sử dụng hệ thống AI thuộc phạm vi kiểm soát của mình trong hoạt động nghề nghiệp, thương mại hoặc cung cấp dịch vụ thì được coi là bên triển khai theo khoản 5 Điều 3 Luật Trí tuệ nhân tạo. Định nghĩa này không bao gồm trường hợp sử dụng cho mục đích cá nhân, phi thương mại. Khoản 2 Điều 1 Thông tư 05/2026/TT-BKHCN cũng ghi nhận cơ quan quản lý nhà nước có thể giữ vai trò bên triển khai hệ thống AI phục vụ hoạt động quản lý nhà nước hoặc cung cấp dịch vụ công.

**Ý bắt buộc:**
1. Cơ quan nhà nước trực tiếp vận hành hệ thống AI được coi là bên triển khai khi sử dụng hệ thống thuộc phạm vi kiểm soát của mình trong hoạt động nghề nghiệp, thương mại hoặc cung cấp dịch vụ, trừ trường hợp sử dụng cho mục đích cá nhân, phi thương mại.
2. Thông tư 05/2026/TT-BKHCN ghi nhận cơ quan quản lý nhà nước có thể giữ vai trò bên triển khai hệ thống AI phục vụ quản lý nhà nước hoặc cung cấp dịch vụ công.

**Căn cứ:** 134-2025-QH15_dieu-3_khoan-5, 05-2026-TT-BKHCN_dieu-1_khoan-2

## t007 · phan_loai · xac_nhan · trung_binh

**Câu hỏi:** Mình thấy cty bảo sp ko có tên trong Danh mục rủi ro cao thì khỏi cần phân loại rủi ro nữa, nói vậy đúng ko?  
*Người hỏi:* người dùng cá nhân · *Mong đợi:* tra_loi

**Đáp án chuẩn:** Không đúng: nếu sản phẩm là hệ thống trí tuệ nhân tạo, nhà cung cấp vẫn phải tự phân loại trước khi đưa hệ thống vào sử dụng và chịu trách nhiệm trước pháp luật về tính chính xác, trung thực của kết quả. Theo khoản 3 Điều 6 Nghị định 142/2026/NĐ-CP, hệ thống không thuộc Danh mục rủi ro cao được phân loại rủi ro trung bình nếu thuộc các trường hợp tại Điều 9; nếu không thuộc cả nhóm cao lẫn trung bình thì được phân loại rủi ro thấp. Theo khoản 1 và khoản 3 Điều 10 Luật Trí tuệ nhân tạo, hệ thống được phân loại rủi ro trung bình hoặc cao phải có hồ sơ phân loại kèm theo, đồng thời nhà cung cấp phải thông báo kết quả phân loại cho Bộ Khoa học và Công nghệ qua Cổng thông tin điện tử một cửa về trí tuệ nhân tạo trước khi đưa vào sử dụng.

**Ý bắt buộc:**
1. Nhận định không thuộc Danh mục rủi ro cao thì được miễn phân loại là sai; nhà cung cấp vẫn phải tự phân loại hệ thống trí tuệ nhân tạo trước khi đưa vào sử dụng và chịu trách nhiệm về kết quả.
2. Hệ thống không thuộc Danh mục rủi ro cao được phân loại rủi ro trung bình nếu thuộc các trường hợp tại Điều 9 Nghị định 142/2026/NĐ-CP, hoặc rủi ro thấp nếu không thuộc cả nhóm cao lẫn trung bình.
3. Hệ thống được phân loại rủi ro trung bình hoặc cao phải có hồ sơ phân loại kèm theo.
4. Nhà cung cấp hệ thống được phân loại rủi ro trung bình hoặc cao phải thông báo kết quả phân loại cho Bộ Khoa học và Công nghệ qua Cổng thông tin điện tử một cửa về trí tuệ nhân tạo trước khi đưa vào sử dụng.

**Căn cứ:** 142-2026-ND-CP_dieu-6_khoan-1, 142-2026-ND-CP_dieu-6_khoan-3, 134-2025-QH15_dieu-10_khoan-1, 134-2025-QH15_dieu-10_khoan-3

## t008 · phan_loai · tinh_huong · kho

**Câu hỏi:** Cong ty toi o Singapore sap cung cap AI cham diem tin dung cho khach hang tai Viet Nam, chung toi can lam gi de xac dinh muc rui ro va thu tuc thong bao tuong ung?  
*Người hỏi:* công ty nước ngoài cung cấp dịch vụ AI tại Việt Nam · *Mong đợi:* tra_loi

**Đáp án chuẩn:** Công ty Singapore cung cấp AI tại Việt Nam thuộc đối tượng áp dụng của Luật Trí tuệ nhân tạo; với vai trò nhà cung cấp, công ty phải tự phân loại hệ thống trước khi đưa vào sử dụng và có hồ sơ phân loại nếu rủi ro trung bình hoặc cao. Riêng mục tự động quyết định cấp tín dụng trong Danh mục rủi ro cao, hệ thống phải thực hiện chấm điểm tín dụng, đánh giá khả năng trả nợ và tự động quyết định cấp tín dụng hoặc giải ngân, đồng thời đưa ra quyết định cuối cùng phê duyệt hoặc từ chối cấp tín dụng, quyết định được sử dụng trực tiếp để cấp tín dụng hoặc giải ngân không có phê duyệt độc lập của cán bộ tín dụng, và khoản vay có mức giá trị theo quy định của Ngân hàng Nhà nước; chỉ thông tin “chấm điểm tín dụng” chưa đủ kết luận thuộc mục này. Nếu không thuộc Danh mục rủi ro cao, hệ thống được phân loại trung bình khi thuộc trường hợp tại Điều 9 Nghị định 142/2026/NĐ-CP, còn lại là rủi ro thấp. Với hệ thống rủi ro trung bình hoặc cao, công ty phải thông báo kết quả phân loại cho Bộ Khoa học và Công nghệ trước khi đưa vào sử dụng qua Cổng thông tin điện tử một cửa về trí tuệ nhân tạo, bảo đảm nội dung theo Điều 12 Nghị định này, bằng biểu mẫu điện tử hoặc gửi tự động qua giao diện lập trình ứng dụng hay phương thức điện tử phù hợp khác theo pháp luật. Cổng tự động cấp mã định danh hệ thống và gửi xác nhận điện tử ngay sau khi hoàn tất gửi thông báo. Nếu cung cấp hệ thống rủi ro cao tại Việt Nam, công ty phải có đầu mối liên hệ hợp pháp tại Việt Nam; nếu hệ thống thuộc diện bắt buộc chứng nhận sự phù hợp trước khi đưa vào sử dụng thì phải có hiện diện thương mại hoặc đại diện được ủy quyền tại Việt Nam.

**Ý bắt buộc:**
1. Công ty Singapore tham gia hoạt động trí tuệ nhân tạo tại Việt Nam thuộc đối tượng áp dụng của Luật Trí tuệ nhân tạo.
2. Nhà cung cấp phải tự phân loại trước khi đưa hệ thống vào sử dụng và có hồ sơ phân loại nếu hệ thống có rủi ro trung bình hoặc cao.
3. Để thuộc mục rủi ro cao về tự động quyết định cấp tín dụng, hệ thống phải thực hiện chấm điểm tín dụng, đánh giá khả năng trả nợ và tự động quyết định cấp tín dụng hoặc giải ngân; đồng thời đưa ra quyết định cuối cùng phê duyệt hoặc từ chối cấp tín dụng, quyết định được sử dụng trực tiếp để cấp tín dụng hoặc giải ngân không có phê duyệt độc lập của cán bộ tín dụng, và khoản vay có mức giá trị theo quy định của Ngân hàng Nhà nước.
4. Hệ thống ngoài Danh mục rủi ro cao được phân loại trung bình nếu thuộc trường hợp tại Điều 9 Nghị định 142/2026/NĐ-CP, còn lại là rủi ro thấp.
5. Nhà cung cấp hệ thống rủi ro trung bình hoặc cao phải thông báo điện tử cho Bộ Khoa học và Công nghệ trước khi sử dụng, với nội dung theo Điều 12, và được tự động cấp mã định danh cùng xác nhận điện tử sau khi gửi.
6. Nhà cung cấp nước ngoài cung cấp hệ thống rủi ro cao tại Việt Nam phải có đầu mối liên hệ hợp pháp tại Việt Nam, và phải có hiện diện thương mại hoặc đại diện được ủy quyền nếu hệ thống thuộc diện bắt buộc chứng nhận sự phù hợp trước khi sử dụng.

**Căn cứ:** 134-2025-QH15_dieu-2, 134-2025-QH15_dieu-10_khoan-1, 33-2026-QD-TTg_linh-vuc-IV_stt-2, 142-2026-ND-CP_dieu-6_khoan-3, 142-2026-ND-CP_dieu-14, 134-2025-QH15_dieu-14_khoan-6

## t009 · phan_loai · nhieu_van_ban · kho

**Câu hỏi:** Công ty tôi cung cấp AI lựa chọn đối tượng nhận quảng cáo; cần đối chiếu tiêu chí trong Luật Trí tuệ nhân tạo với Danh mục tại Quyết định 33/2026/QĐ-TTg như thế nào để xác định mức rủi ro?  
*Người hỏi:* công ty truyền thông, quảng cáo · *Mong đợi:* tra_loi

**Đáp án chuẩn:** Công ty cần đánh giá mức độ tác động đến quyền con người, an toàn, an ninh; lĩnh vực sử dụng, đặc biệt lĩnh vực thiết yếu hoặc liên quan trực tiếp đến lợi ích công cộng; phạm vi người sử dụng và quy mô ảnh hưởng theo khoản 2 Điều 9 Luật Trí tuệ nhân tạo. Tiếp đó, đối chiếu chức năng thực tế và đầy đủ điều kiện áp dụng của từng mục trong Phụ lục Quyết định 33/2026/QĐ-TTg, đồng thời xét tiêu chí gây thiệt hại đáng kể và điều kiện không được loại trừ theo Điều 2 Quyết định này. Khoản 2 Điều 8 Nghị định 142/2026/NĐ-CP quy định các trường hợp không được đề xuất đưa vào Danh mục, với điều kiện cụ thể về tác vụ dữ liệu, giám sát thực chất của con người, hoạt động nội bộ hoặc chức năng tham khảo, nên không thể chỉ dựa vào tên gọi các trường hợp này. Bốn văn bản không có mục riêng về AI lựa chọn đối tượng nhận quảng cáo, nên mô tả này chưa đủ để kết luận mức rủi ro. Theo khoản 3 Điều 6 Nghị định 142, hệ thống thuộc Danh mục được phân loại rủi ro cao; ngoài Danh mục thì xét Điều 9 về rủi ro trung bình, và nếu không thuộc cả hai nhóm thì là rủi ro thấp. Không tự động xếp AI lựa chọn người nhận quảng cáo vào nhóm trung bình: phải có khả năng gây nhầm lẫn, tác động hoặc thao túng do người sử dụng không nhận biết chủ thể tương tác là AI hoặc nội dung do AI tạo ra, đồng thời không thuộc trường hợp không phân loại rủi ro trung bình tại khoản 3 Điều 9.

**Ý bắt buộc:**
1. Việc phân loại phải căn cứ mức độ tác động đến quyền con người, an toàn, an ninh; lĩnh vực sử dụng; phạm vi người sử dụng và quy mô ảnh hưởng.
2. Quyết định 33 xác định rủi ro cao theo tiêu chí có thể gây thiệt hại đáng kể và không được loại trừ theo khoản 2 Điều 8 Nghị định 142.
3. Khoản 2 Điều 8 Nghị định 142 quy định hệ thống dù thuộc tiêu chí tại khoản 1 nhưng không được đề xuất đưa vào Danh mục khi đáp ứng một trong các tiêu chí tại các điểm a–d; cần kiểm tra đầy đủ điều kiện tương ứng về tác vụ dữ liệu, giám sát thực chất của con người, hoạt động nội bộ hoặc chức năng tham khảo.
4. Hệ thống thuộc Danh mục được phân loại rủi ro cao; ngoài Danh mục phải xét rủi ro trung bình trước khi kết luận rủi ro thấp.
5. Nhà cung cấp phải xét đồng thời điều kiện rủi ro trung bình và các trường hợp không phân loại vào nhóm này, không suy ra chỉ từ chức năng lựa chọn người nhận quảng cáo.
6. Các văn bản trong thư mục không quy định riêng mức rủi ro cho AI lựa chọn đối tượng nhận quảng cáo.

**Căn cứ:** 134-2025-QH15_dieu-9_khoan-2, 33-2026-QD-TTg_dieu-2, 142-2026-ND-CP_dieu-8_khoan-2, 142-2026-ND-CP_dieu-6_khoan-3, 142-2026-ND-CP_dieu-9

## t010 · minh_bach · thu_tuc · trung_binh

**Câu hỏi:** Phòng nhân sự phải thông báo việc dùng AI phỏng vấn vào thời điểm nào trong quy trình tiếp nhận ứng viên?  
*Người hỏi:* phòng nhân sự dùng AI tuyển dụng · *Mong đợi:* tra_loi

**Đáp án chuẩn:** Trong phạm vi bốn văn bản được kiểm tra, không có quy định một thời điểm cụ thể trong quy trình tiếp nhận ứng viên mà phòng nhân sự phải thông báo việc dùng AI phỏng vấn. Nếu hệ thống AI tương tác trực tiếp với ứng viên, khoản 1 Điều 11 Luật Trí tuệ nhân tạo yêu cầu nhà cung cấp bảo đảm hệ thống được thiết kế và vận hành để ứng viên nhận biết khi đang tương tác với hệ thống, trừ trường hợp pháp luật có quy định khác. Theo khoản 5 Điều 11, nhà cung cấp và bên triển khai có trách nhiệm duy trì thông tin minh bạch theo Điều này trong suốt quá trình cung cấp hệ thống, sản phẩm hoặc nội dung cho người sử dụng.

**Ý bắt buộc:**
1. Không có quy định cụ thể về thời điểm phòng nhân sự phải thông báo việc dùng AI phỏng vấn trong quy trình tiếp nhận ứng viên.
2. Đối với hệ thống AI tương tác trực tiếp với con người, nhà cung cấp phải bảo đảm người sử dụng nhận biết khi đang tương tác với hệ thống, trừ trường hợp pháp luật có quy định khác.
3. Nhà cung cấp và bên triển khai có trách nhiệm duy trì thông tin minh bạch trong suốt quá trình cung cấp hệ thống, sản phẩm hoặc nội dung cho người sử dụng.

**Căn cứ:** 134-2025-QH15_dieu-11_khoan-1, 134-2025-QH15_dieu-11_khoan-5

## t011 · minh_bach · tien_de_sai · trung_binh

**Câu hỏi:** Mình biết chatbot chỉ phải nói nó là AI khi khách chủ động hỏi, vậy cty nên soạn câu trả lời xác nhận thế nào cho đúng?  
*Người hỏi:* startup làm ứng dụng AI · *Mong đợi:* tra_loi

**Đáp án chuẩn:** Tiền đề “chatbot chỉ phải nói là AI khi khách chủ động hỏi” là sai: khoản 1 Điều 11 Luật 134/2025/QH15 yêu cầu nhà cung cấp bảo đảm hệ thống AI tương tác trực tiếp với con người được thiết kế và vận hành để người sử dụng nhận biết khi đang tương tác với hệ thống, trừ trường hợp pháp luật có quy định khác. Nhà cung cấp và bên triển khai phải duy trì thông tin minh bạch theo Điều này trong suốt quá trình cung cấp hệ thống, sản phẩm hoặc nội dung cho người sử dụng. Bốn văn bản trong thư mục không quy định mẫu câu xác nhận bắt buộc riêng cho chatbot. Công ty có thể dùng thông báo “Bạn đang tương tác với chatbot trí tuệ nhân tạo (AI) của công ty” để giúp khách nhận biết khi tương tác, thay vì chờ khách hỏi; đây là câu gợi ý, không phải mẫu câu do văn bản quy định.

**Ý bắt buộc:**
1. Tiền đề chỉ phải xác nhận là AI khi khách chủ động hỏi là sai; nhà cung cấp phải bảo đảm hệ thống AI tương tác trực tiếp với con người được thiết kế và vận hành để người sử dụng nhận biết khi đang tương tác với hệ thống, trừ trường hợp pháp luật có quy định khác.
2. Nhà cung cấp và bên triển khai có trách nhiệm duy trì thông tin minh bạch trong suốt quá trình cung cấp hệ thống, sản phẩm hoặc nội dung cho người sử dụng.
3. Các văn bản trong thư mục không quy định mẫu câu xác nhận bắt buộc riêng cho chatbot.

**Căn cứ:** 134-2025-QH15_dieu-11_khoan-1, 134-2025-QH15_dieu-11_khoan-5

## t012 · minh_bach · rong · kho

**Câu hỏi:** Shop toi dung AI thi phai noi voi khach nhung gi?  
*Người hỏi:* chủ shop bán hàng online · *Mong đợi:* tra_loi

**Đáp án chuẩn:** Nếu khách tương tác trực tiếp với AI, nhà cung cấp phải bảo đảm khách nhận biết đang tương tác với AI, trừ trường hợp pháp luật có quy định khác. Khi shop là bên triển khai, shop phải cung cấp thông tin về mục đích sử dụng, phạm vi áp dụng, điều kiện sử dụng và các hạn chế của hệ thống. Khi cung cấp ra công cộng nội dung do AI tạo hoặc chỉnh sửa có khả năng gây nhầm lẫn về tính xác thực của sự kiện, nhân vật hoặc nguồn gốc nội dung, shop phải thông báo rõ ràng, trừ trường hợp pháp luật có quy định khác. Âm thanh, hình ảnh hoặc video do AI tạo hoặc chỉnh sửa nhằm mô phỏng, giả lập ngoại hình, giọng nói người thật hoặc tái hiện sự kiện thực tế phải được gắn nhãn dễ nhận biết, với ngoại lệ theo pháp luật đối với việc tái hiện sự kiện thực tế. Thông báo và nhãn phải rõ ràng, dễ hiểu, dễ nhận biết, xuất hiện trước hoặc khi khách tiếp cận nội dung, không che giấu hoặc làm giảm khả năng nhận biết bản chất nội dung, phù hợp loại hình và phương thức cung cấp, không cản trở đáng kể việc hiển thị, trình diễn hoặc sử dụng. Shop được miễn gắn nhãn hiển thị đối với chỉnh sửa kỹ thuật nhằm cải thiện chất lượng âm thanh, hình ảnh hoặc video mà không đổi bản chất hoặc ngữ cảnh chính; hỗ trợ sửa chính tả, ngữ pháp, tóm tắt, diễn giải hoặc dịch thuật mà không làm sai lệch nội dung cơ bản của văn bản gốc; nội dung nội bộ không cung cấp ra công cộng; và nội dung tạo trong quá trình nghiên cứu, phát triển hoặc thử nghiệm trong môi trường kiểm soát không cung cấp ra công cộng.

**Ý bắt buộc:**
1. Với hệ thống AI tương tác trực tiếp với con người, nhà cung cấp phải bảo đảm người sử dụng nhận biết đang tương tác với AI, trừ trường hợp pháp luật có quy định khác.
2. Nhà cung cấp và bên triển khai phải cung cấp thông tin về mục đích sử dụng, phạm vi áp dụng, điều kiện sử dụng và các hạn chế của hệ thống AI.
3. Bên triển khai phải thông báo rõ ràng khi cung cấp ra công cộng nội dung do AI tạo hoặc chỉnh sửa có khả năng gây nhầm lẫn về tính xác thực của sự kiện, nhân vật hoặc nguồn gốc nội dung, trừ trường hợp pháp luật có quy định khác.
4. Bên triển khai phải gắn nhãn dễ nhận biết cho âm thanh, hình ảnh hoặc video do AI tạo hoặc chỉnh sửa mô phỏng ngoại hình, giọng nói người thật hoặc tái hiện sự kiện thực tế, với ngoại lệ theo pháp luật đối với việc tái hiện sự kiện thực tế.
5. Thông báo và nhãn phải rõ ràng, dễ hiểu, dễ nhận biết, xuất hiện trước hoặc khi người tiếp nhận tiếp cận nội dung, không che giấu bản chất nội dung, phù hợp cách cung cấp và không gây cản trở đáng kể việc sử dụng nội dung.
6. Bên triển khai không phải gắn nhãn hiển thị đối với: chỉnh sửa kỹ thuật nhằm cải thiện chất lượng âm thanh, hình ảnh hoặc video mà không thay đổi bản chất hoặc ngữ cảnh chính; văn bản được hỗ trợ sửa lỗi chính tả, ngữ pháp, tóm tắt, diễn giải hoặc dịch thuật mà không làm sai lệch nội dung cơ bản của văn bản gốc; nội dung dùng trong nội bộ cơ quan, tổ chức, doanh nghiệp và không cung cấp ra công cộng; nội dung được tạo trong quá trình nghiên cứu, phát triển hoặc thử nghiệm trong môi trường kiểm soát và không cung cấp ra công cộng.

**Căn cứ:** 134-2025-QH15_dieu-11_khoan-1, 142-2026-ND-CP_dieu-16_khoan-2, 142-2026-ND-CP_dieu-18_khoan-1, 142-2026-ND-CP_dieu-18_khoan-2, 142-2026-ND-CP_dieu-18_khoan-3, 142-2026-ND-CP_dieu-18_khoan-4

## t013 · rui_ro_cao · tra_cuu · de

**Câu hỏi:** Công ty tài chính phải tổ chức giám sát của con người đối với AI rủi ro cao như thế nào?  
*Người hỏi:* ngân hàng, công ty tài chính · *Mong đợi:* tra_loi

**Đáp án chuẩn:** Khi là bên triển khai AI rủi ro cao, công ty tài chính phải vận hành, giám sát hệ thống đúng mục đích, phạm vi và mức độ rủi ro đã phân loại, không làm phát sinh rủi ro mới hoặc rủi ro cao hơn, đồng thời bảo đảm khả năng can thiệp của con người trong quá trình sử dụng. Công ty phải tổ chức quản lý rủi ro phù hợp với mục đích sử dụng, phạm vi triển khai, mức độ rủi ro và hướng dẫn kỹ thuật của nhà cung cấp. Công ty phải tổ chức giám sát để phát hiện sai lệch, rủi ro hoặc sự cố, thiết lập và duy trì cơ chế giám sát, can thiệp của con người theo quy định của pháp luật. Khi phát hiện hệ thống hoạt động không đúng mục đích hoặc phát sinh rủi ro mới, công ty phải áp dụng biện pháp hạn chế hoặc kiểm soát rủi ro trong phạm vi quyền kiểm soát của mình; khi hệ thống thay đổi đáng kể hoặc phát sinh sự cố, phải phối hợp với nhà cung cấp rà soát, cập nhật biện pháp quản lý rủi ro. Việc sử dụng AI không làm thay đổi, chuyển giao hoặc loại trừ thẩm quyền, trách nhiệm của cơ quan, tổ chức, cá nhân có thẩm quyền theo pháp luật. Nếu đồng thời là nhà cung cấp AI rủi ro cao, công ty còn phải thiết kế hệ thống bảo đảm khả năng giám sát và can thiệp của con người.

**Ý bắt buộc:**
1. Công ty tài chính khi là bên triển khai AI rủi ro cao phải giám sát đúng mục đích, phạm vi, mức độ rủi ro đã phân loại và bảo đảm khả năng can thiệp của con người.
2. Bên triển khai phải tổ chức quản lý rủi ro phù hợp với mục đích sử dụng, phạm vi triển khai, mức độ rủi ro và hướng dẫn kỹ thuật của nhà cung cấp.
3. Bên triển khai phải tổ chức giám sát để phát hiện sai lệch, rủi ro, sự cố và thiết lập, duy trì cơ chế giám sát, can thiệp của con người trong quá trình sử dụng.
4. Bên triển khai phải kiểm soát rủi ro trong phạm vi quyền kiểm soát của mình khi hệ thống dùng sai mục đích hoặc phát sinh rủi ro mới, và phối hợp với nhà cung cấp cập nhật biện pháp khi hệ thống thay đổi đáng kể hoặc có sự cố.
5. Nếu công ty tài chính đồng thời là nhà cung cấp AI rủi ro cao, công ty có trách nhiệm thiết kế hệ thống bảo đảm khả năng giám sát và can thiệp của con người.
6. Việc sử dụng AI không làm thay đổi, chuyển giao hoặc loại trừ thẩm quyền, trách nhiệm của cơ quan, tổ chức, cá nhân có thẩm quyền; phải bảo đảm sự giám sát, kiểm soát và khả năng can thiệp của con người khi vận hành.

**Căn cứ:** 134-2025-QH15_dieu-14_khoan-2, 142-2026-ND-CP_dieu-15_khoan-4, 142-2026-ND-CP_dieu-15_khoan-5, 134-2025-QH15_dieu-14_khoan-1, 33-2026-QD-TTg_dieu-1_khoan-2

## t014 · rui_ro_cao · xac_nhan · trung_binh

**Câu hỏi:** Phòng khám dùng AI rủi ro cao phải duy trì việc theo dõi hiệu năng trong suốt quá trình vận hành, đúng hay sai?  
*Người hỏi:* bệnh viện, phòng khám · *Mong đợi:* tra_loi

**Đáp án chuẩn:** Đúng nếu “theo dõi hiệu năng” được hiểu là giám sát hoạt động của hệ thống trong quá trình triển khai và vận hành. Phòng khám sử dụng AI thuộc phạm vi kiểm soát của mình để cung cấp dịch vụ là bên triển khai theo khoản 5 Điều 3 Luật 134/2025/QH15. Với AI rủi ro cao, điểm b và c khoản 5 Điều 15 Nghị định 142/2026/NĐ-CP yêu cầu bên triển khai tổ chức giám sát hoạt động nhằm phát hiện sai lệch, rủi ro hoặc sự cố, đồng thời thiết lập và duy trì cơ chế giám sát, can thiệp của con người trong quá trình sử dụng. Tuy nhiên, bốn văn bản được kiểm tra không quy định riêng nghĩa vụ mang tên “theo dõi hiệu năng trong suốt quá trình vận hành”.

**Ý bắt buộc:**
1. Phòng khám sử dụng AI thuộc phạm vi kiểm soát của mình để cung cấp dịch vụ là bên triển khai.
2. Bên triển khai AI rủi ro cao phải giám sát hoạt động và duy trì cơ chế giám sát, can thiệp của con người trong quá trình sử dụng.
3. Các văn bản không quy định riêng nghĩa vụ “theo dõi hiệu năng trong suốt quá trình vận hành”.

**Căn cứ:** 134-2025-QH15_dieu-3_khoan-5, 142-2026-ND-CP_dieu-15_khoan-5

## t015 · rui_ro_cao · tinh_huong · kho

**Câu hỏi:** Trường mình dùng AI xét tuyển đã dc xác định là rủi ro cao, giờ cty cung cấp đổi sang mô hình mới ngay trước kỳ tuyển sinh thì trường phải làm gì trước khi dùng tiếp?  
*Người hỏi:* trường học · *Mong đợi:* tra_loi

**Đáp án chuẩn:** Trước khi dùng tiếp, trường với vai trò bên triển khai phải phối hợp với nhà cung cấp rà soát, cập nhật biện pháp quản lý rủi ro nếu việc đổi mô hình là thay đổi đáng kể. Nếu thay đổi mô hình có thể ảnh hưởng đến tính chính xác, độ tin cậy, mức độ an toàn hoặc khả năng kiểm soát của hệ thống, nhà cung cấp phải đánh giá lại sự phù hợp; trường cần bảo đảm hệ thống đáp ứng điều kiện về kết quả đánh giá sự phù hợp trước khi sử dụng mô hình mới. Nâng cấp phiên bản không làm thay đổi việc đáp ứng các yêu cầu tại Điều 14 Luật Trí tuệ nhân tạo không được coi là thay đổi đáng kể. Nhà cung cấp phải duy trì sự phù hợp và công khai thông tin về kết quả đánh giá trên Cổng thông tin điện tử một cửa về trí tuệ nhân tạo khi cập nhật kết quả đánh giá lại. Khi tiếp tục sử dụng, trường phải vận hành đúng mục đích, điều kiện, giới hạn sử dụng do nhà cung cấp xác định và duy trì giám sát, khả năng can thiệp của con người.

**Ý bắt buộc:**
1. Trường với vai trò bên triển khai phải phối hợp nhà cung cấp rà soát, cập nhật biện pháp quản lý rủi ro khi hệ thống có thay đổi đáng kể.
2. Nhà cung cấp phải đánh giá lại sự phù hợp nếu thay đổi mô hình có thể ảnh hưởng đến tính chính xác, độ tin cậy, mức độ an toàn hoặc khả năng kiểm soát của hệ thống.
3. Nâng cấp phiên bản không làm thay đổi việc đáp ứng các yêu cầu tại Điều 14 Luật Trí tuệ nhân tạo không được coi là thay đổi đáng kể.
4. Kết quả đánh giá sự phù hợp là điều kiện để hệ thống AI rủi ro cao được phép đưa vào sử dụng.
5. Trường phải vận hành đúng mục đích, điều kiện, giới hạn sử dụng và duy trì giám sát, khả năng can thiệp của con người.
6. Nhà cung cấp phải duy trì sự phù hợp và công khai thông tin về kết quả đánh giá sự phù hợp trên Cổng thông tin điện tử một cửa về trí tuệ nhân tạo khi cập nhật kết quả đánh giá lại.

**Căn cứ:** 142-2026-ND-CP_dieu-15_khoan-5, 142-2026-ND-CP_dieu-13_khoan-1, 134-2025-QH15_dieu-13_khoan-3, 142-2026-ND-CP_dieu-13_khoan-6

## t016 · su_co_che_tai · thu_tuc · trung_binh

**Câu hỏi:** Co quan toi phat hien su co AI lam sai lech ket qua xu ly ho so thi phai gui bao cao ban dau cho co quan nao va trong bao lau?  
*Người hỏi:* cơ quan nhà nước · *Mong đợi:* tra_loi

**Đáp án chuẩn:** Chỉ từ mô tả AI làm sai lệch kết quả xử lý hồ sơ chưa đủ kết luận đây là sự cố nghiêm trọng theo khoản 1 Điều 19 Nghị định 142/2026/NĐ-CP để áp dụng nghĩa vụ báo cáo sơ bộ. Nếu thuộc trường hợp này, nhà cung cấp hoặc bên triển khai phải gửi báo cáo sơ bộ cho cơ quan nhà nước có thẩm quyền qua Cổng thông tin điện tử một cửa về trí tuệ nhân tạo, theo Mẫu AI01a đối với tổ chức; Bộ Khoa học và Công nghệ có nhiệm vụ tổ chức tiếp nhận, tổng hợp thông tin sự cố qua Cổng theo khoản 3 Điều 41. Thời hạn là 72 giờ kể từ thời điểm xác nhận sự cố đối với các trường hợp tại điểm a, điểm d khoản 1 Điều 19 (thiệt hại về tính mạng, tổn hại nghiêm trọng sức khỏe, gián đoạn nghiêm trọng dịch vụ công hoặc dịch vụ thiết yếu, hoặc ảnh hưởng đến an ninh quốc gia, trật tự, an toàn xã hội) và trường hợp không thể kiểm soát tại điểm c (xâm phạm nghiêm trọng quyền con người, quyền và lợi ích hợp pháp của cơ quan, tổ chức, cá nhân). Các sự cố nghiêm trọng còn lại phải được báo cáo sơ bộ trong 05 ngày làm việc kể từ thời điểm xác nhận sự cố. Thời điểm xác nhận là khi có đủ cơ sở thông tin ban đầu xác định sự cố đã thực sự xảy ra và có khả năng cao bắt nguồn từ lỗi hệ thống AI, không đợi hoàn thành điều tra toàn diện nguyên nhân kỹ thuật.

**Ý bắt buộc:**
1. Việc làm sai lệch kết quả xử lý hồ sơ chỉ thuộc nghĩa vụ báo cáo sơ bộ tại Điều 19 khi sự cố đáp ứng điều kiện về sự cố nghiêm trọng.
2. Nhà cung cấp hoặc bên triển khai phải báo cáo sơ bộ sự cố nghiêm trọng cho cơ quan nhà nước có thẩm quyền qua Cổng thông tin điện tử một cửa về trí tuệ nhân tạo, theo Mẫu AI01a đối với tổ chức.
3. Thời hạn báo cáo sơ bộ là 72 giờ kể từ thời điểm xác nhận đối với sự cố thuộc điểm a, điểm d hoặc trường hợp không thể kiểm soát tại điểm c khoản 1 Điều 19.
4. Các sự cố nghiêm trọng còn lại phải được báo cáo sơ bộ trong thời hạn 05 ngày làm việc kể từ thời điểm xác nhận sự cố.
5. Thời điểm xác nhận sự cố được tính khi có đủ cơ sở thông tin ban đầu xác định sự cố thực sự xảy ra và có khả năng cao bắt nguồn từ lỗi hệ thống AI, không đợi điều tra toàn diện nguyên nhân kỹ thuật.

**Căn cứ:** 142-2026-ND-CP_dieu-19_khoan-1, 142-2026-ND-CP_dieu-19_khoan-3

## t017 · su_co_che_tai · tien_de_sai · trung_binh

**Câu hỏi:** Vì AI không có tư cách pháp nhân nên tôi chắc chắn không thể yêu cầu bất kỳ ai bồi thường khi bị AI gây thiệt hại, vậy tôi chỉ còn cách tự chịu tổn thất phải không?  
*Người hỏi:* người dùng cá nhân · *Mong đợi:* tra_loi

**Đáp án chuẩn:** Không, việc AI không có tư cách pháp nhân không có nghĩa là bạn không thể yêu cầu ai bồi thường và phải tự chịu tổn thất. Theo khoản 1 Điều 29 Luật Trí tuệ nhân tạo, tổ chức, cá nhân vi phạm pháp luật liên quan đến trí tuệ nhân tạo mà gây thiệt hại thì phải bồi thường theo pháp luật dân sự. Theo khoản 2, nếu hệ thống trí tuệ nhân tạo có rủi ro cao được quản lý, vận hành và sử dụng đúng quy định nhưng vẫn phát sinh thiệt hại thì bên triển khai phải bồi thường cho người bị thiệt hại. Theo khoản 3, trách nhiệm tại khoản 2 được miễn trừ khi thiệt hại hoàn toàn do lỗi cố ý của người bị thiệt hại; hoặc khi thiệt hại xảy ra trong trường hợp bất khả kháng hoặc tình thế cấp thiết, trừ trường hợp pháp luật có quy định khác. Theo khoản 4, nếu hệ thống bị bên thứ ba xâm nhập, chiếm quyền điều khiển hoặc can thiệp trái pháp luật thì bên thứ ba phải bồi thường; bên triển khai, nhà cung cấp có lỗi trong việc để xảy ra việc đó phải liên đới bồi thường theo pháp luật dân sự.

**Ý bắt buộc:**
1. Suy luận rằng không thể yêu cầu ai bồi thường vì AI không có tư cách pháp nhân là sai, vì tổ chức, cá nhân vi phạm pháp luật liên quan đến trí tuệ nhân tạo mà gây thiệt hại phải bồi thường theo pháp luật dân sự.
2. Bên triển khai phải bồi thường khi hệ thống trí tuệ nhân tạo có rủi ro cao được quản lý, vận hành và sử dụng đúng quy định nhưng vẫn phát sinh thiệt hại, trừ các trường hợp miễn trừ tại khoản 3 Điều 29.
3. Trách nhiệm bồi thường tại khoản 2 Điều 29 được miễn trừ khi thiệt hại hoàn toàn do lỗi cố ý của người bị thiệt hại hoặc xảy ra trong trường hợp bất khả kháng hoặc tình thế cấp thiết, trừ trường hợp pháp luật có quy định khác.
4. Bên thứ ba xâm nhập, chiếm quyền điều khiển hoặc can thiệp trái pháp luật vào hệ thống phải bồi thường, còn bên triển khai, nhà cung cấp có lỗi trong việc để xảy ra việc đó phải liên đới bồi thường theo pháp luật dân sự.

**Căn cứ:** 134-2025-QH15_dieu-29_khoan-1, 134-2025-QH15_dieu-29_khoan-2, 134-2025-QH15_dieu-29_khoan-3, 134-2025-QH15_dieu-29_khoan-4

## t018 · su_co_che_tai · nhieu_van_ban · kho

**Câu hỏi:** Công ty chúng tôi ở nước ngoài có dịch vụ AI gây gián đoạn hoạt động của khách hàng Việt Nam; cần kết hợp tiêu chí về sự cố trong Luật Trí tuệ nhân tạo với hướng dẫn tại Nghị định 142/2026/NĐ-CP như thế nào để xác định có phải báo cáo không?  
*Người hỏi:* công ty nước ngoài cung cấp dịch vụ AI tại Việt Nam · *Mong đợi:* tra_loi

**Đáp án chuẩn:** Công ty nước ngoài thuộc đối tượng áp dụng của Nghị định 142/2026/NĐ-CP nếu tham gia hoạt động trí tuệ nhân tạo tại Việt Nam. Cần đọc kết hợp khoản 8 Điều 3 Luật Trí tuệ nhân tạo, bao gồm cả sự kiện gây ra hoặc có nguy cơ gây ra thiệt hại đáng kể và trường hợp làm gián đoạn hệ thống thông tin quan trọng về an ninh quốc gia, với các hậu quả cụ thể tại khoản 1 Điều 19 Nghị định. Thông tin dịch vụ AI gây gián đoạn hoạt động khách hàng chưa đủ để kết luận: cần xác định có thiệt hại đáng kể về tài sản, ảnh hưởng nghiêm trọng đến hoạt động của tổ chức hoặc hậu quả khác được liệt kê hay không, đồng thời không bỏ qua tiêu chí nguy cơ gây thiệt hại trong Luật. Khi xảy ra sự cố nghiêm trọng, nhà phát triển, nhà cung cấp phải khẩn trương áp dụng biện pháp kỹ thuật để khắc phục, tạm dừng hoặc thu hồi hệ thống, đồng thời thông báo cho cơ quan có thẩm quyền theo điểm a khoản 2 Điều 12 Luật. Theo khoản 3 Điều 19 Nghị định, nhà cung cấp hoặc bên triển khai phải báo cáo sơ bộ qua Cổng thông tin điện tử một cửa về trí tuệ nhân tạo, dùng Mẫu AI01a đối với tổ chức, trong 72 giờ đối với sự cố nghiêm trọng có tính khẩn cấp tại điểm a, điểm d và trường hợp không thể kiểm soát tại điểm c khoản 1 Điều 19, hoặc trong 05 ngày làm việc đối với sự cố nghiêm trọng còn lại, kể từ thời điểm xác nhận sự cố. Thời điểm xác nhận là khi có đủ cơ sở thông tin ban đầu xác định sự cố đã thực sự xảy ra và có khả năng cao bắt nguồn từ lỗi của hệ thống AI, không đợi hoàn thành điều tra toàn diện nguyên nhân kỹ thuật.

**Ý bắt buộc:**
1. Tiêu chí sự cố nghiêm trọng trong Luật bao gồm cả thiệt hại đáng kể đã xảy ra hoặc có nguy cơ xảy ra và việc gián đoạn hệ thống thông tin quan trọng về an ninh quốc gia.
2. Để đánh giá gián đoạn hoạt động khách hàng theo Nghị định, cần xác định mức ảnh hưởng nghiêm trọng đến hoạt động của tổ chức hoặc hậu quả khác được liệt kê, không mặc nhiên coi mọi gián đoạn là sự cố nghiêm trọng.
3. Khi xảy ra sự cố nghiêm trọng, nhà phát triển, nhà cung cấp phải khẩn trương khắc phục, tạm dừng hoặc thu hồi hệ thống và thông báo cho cơ quan có thẩm quyền.
4. Nhà cung cấp hoặc bên triển khai phải báo cáo sơ bộ qua Cổng theo mẫu tương ứng trong 72 giờ đối với các trường hợp khẩn cấp được quy định, hoặc 05 ngày làm việc đối với sự cố nghiêm trọng còn lại, kể từ thời điểm xác nhận sự cố.
5. Thời điểm xác nhận sự cố dựa trên thông tin ban đầu về sự cố thực tế và khả năng cao bắt nguồn từ lỗi hệ thống AI, không chờ điều tra toàn diện.

**Căn cứ:** 134-2025-QH15_dieu-3_khoan-8, 142-2026-ND-CP_dieu-19_khoan-1, 134-2025-QH15_dieu-12_khoan-2, 142-2026-ND-CP_dieu-19_khoan-3

## t019 · cam_dao_duc_cong · tra_cuu · de

**Câu hỏi:** Cty quảng cáo dùng AI giả giọng người nổi tiếng để khiến khách tưởng họ giới thiệu sp thì có bị cấm ko?  
*Người hỏi:* công ty truyền thông, quảng cáo · *Mong đợi:* tra_loi

**Đáp án chuẩn:** Hành vi dùng AI giả giọng người nổi tiếng để khiến khách tưởng họ giới thiệu sản phẩm bị nghiêm cấm theo điểm b khoản 2 Điều 7 Luật Trí tuệ nhân tạo nếu việc lừa dối hoặc thao túng nhận thức, hành vi được thực hiện có chủ đích và có hệ thống, gây tổn hại nghiêm trọng đến quyền, lợi ích hợp pháp của con người; dữ kiện câu hỏi chưa đủ để kết luận đáp ứng toàn bộ các điều kiện này. Công ty là bên triển khai nếu sử dụng hệ thống AI thuộc phạm vi kiểm soát của mình trong hoạt động thương mại hoặc cung cấp dịch vụ. Theo khoản 3 Điều 11, khi cung cấp ra công cộng âm thanh AI có khả năng gây nhầm lẫn về tính xác thực của nhân vật, bên triển khai phải thông báo rõ ràng, trừ trường hợp pháp luật có quy định khác. Âm thanh AI mô phỏng giọng người thật trong quảng cáo này phải được gắn nhãn dễ nhận biết theo điểm a khoản 2 Điều 18 Nghị định 142/2026/NĐ-CP. Theo khoản 3 Điều 18, thông báo và nhãn phải rõ ràng, dễ hiểu, dễ nhận biết, được thực hiện trước hoặc tại thời điểm người tiếp nhận tiếp cận nội dung và không được thiết kế để che giấu hoặc làm giảm khả năng nhận biết bản chất nội dung. Việc che giấu thông tin bắt buộc phải công khai, minh bạch hoặc tẩy xóa, làm sai lệch nhãn bắt buộc cũng bị nghiêm cấm theo khoản 5 Điều 7 Luật Trí tuệ nhân tạo.

**Ý bắt buộc:**
1. Dùng AI giả giọng để lừa dối hoặc thao túng nhận thức, hành vi bị nghiêm cấm khi có chủ đích và có hệ thống, gây tổn hại nghiêm trọng đến quyền, lợi ích hợp pháp của con người.
2. Công ty là bên triển khai nếu sử dụng hệ thống AI thuộc phạm vi kiểm soát của mình trong hoạt động quảng cáo thương mại hoặc cung cấp dịch vụ.
3. Bên triển khai phải thông báo rõ ràng khi cung cấp ra công cộng âm thanh AI có khả năng gây nhầm lẫn về tính xác thực của nhân vật, trừ trường hợp pháp luật có quy định khác.
4. Bên triển khai phải gắn nhãn dễ nhận biết đối với âm thanh được AI tạo ra hoặc chỉnh sửa để mô phỏng giọng nói của người thật.
5. Thông báo và nhãn phải rõ ràng, dễ nhận biết, được thực hiện trước hoặc khi người tiếp nhận tiếp cận nội dung và không được che giấu bản chất nội dung.

**Căn cứ:** 134-2025-QH15_dieu-7_khoan-2, 134-2025-QH15_dieu-3_khoan-5, 134-2025-QH15_dieu-11_khoan-3, 142-2026-ND-CP_dieu-18_khoan-2, 142-2026-ND-CP_dieu-18_khoan-3

## t020 · cam_dao_duc_cong · xac_nhan · trung_binh

**Câu hỏi:** Don vi su nghiep cong lap cua toi trien khai AI tuyen dung thi chi can danh gia tac dong khi he thong da gay hau qua, dung hay sai?  
*Người hỏi:* phòng nhân sự dùng AI tuyển dụng · *Mong đợi:* tra_loi

**Đáp án chuẩn:** Sai về quan niệm chỉ đánh giá tác động sau khi đã gây hậu quả: khi thuộc diện phải đánh giá theo Điều 20 Nghị định 142/2026/NĐ-CP, người đứng đầu cơ quan, đơn vị triển khai phải tổ chức lập, phê duyệt báo cáo trước khi đưa hệ thống vào sử dụng. Khoản 3 Điều 27 Luật quy định nghĩa vụ lập báo cáo đối với cơ quan vận hành hệ thống có rủi ro cao hoặc có tác động đáng kể đến quyền con người, công bằng xã hội hoặc lợi ích công cộng trong quản lý nhà nước và cung cấp dịch vụ công. Khoản 1 Điều 20 Nghị định quy định cơ quan nhà nước đánh giá đối với hệ thống rủi ro cao hoặc hệ thống thuộc khoản 7 có kết quả được dùng làm căn cứ trực tiếp để người có thẩm quyền xem xét, quyết định ban hành quyết định hành chính. Khoản 7 bao gồm hệ thống dùng để phân loại, chấm điểm, đánh giá hoặc xếp hạng tổ chức, cá nhân, nhưng riêng chức năng này chưa đủ để kết luận nghĩa vụ theo điểm b khoản 1. Với hệ thống thuộc khoản 1, nếu thay đổi mục đích sử dụng, chức năng chính, nguồn dữ liệu đầu vào chủ yếu hoặc phạm vi đối tượng áp dụng làm phát sinh rủi ro mới hoặc thay đổi mức độ rủi ro thì phải đánh giá bổ sung trước khi tiếp tục sử dụng. Tuy nhiên, chỉ từ thông tin đơn vị sự nghiệp công lập triển khai AI tuyển dụng, chưa đủ căn cứ trong bốn văn bản để khẳng định hệ thống cụ thể chắc chắn thuộc diện bắt buộc đánh giá tác động.

**Ý bắt buộc:**
1. Tiền đề chỉ đánh giá tác động sau khi hệ thống gây hậu quả là sai; khi thuộc diện phải đánh giá, người đứng đầu cơ quan, đơn vị triển khai phải tổ chức lập, phê duyệt báo cáo trước khi đưa hệ thống vào sử dụng.
2. Trong quản lý nhà nước và cung cấp dịch vụ công, cơ quan vận hành hệ thống có rủi ro cao hoặc có tác động đáng kể đến quyền con người, công bằng xã hội hoặc lợi ích công cộng phải lập báo cáo đánh giá tác động.
3. Điều 20 Nghị định 142/2026/NĐ-CP yêu cầu cơ quan nhà nước đánh giá tác động đối với hệ thống rủi ro cao hoặc hệ thống thuộc khoản 7 có kết quả được dùng làm căn cứ trực tiếp để xem xét, quyết định ban hành quyết định hành chính.
4. Cơ quan, đơn vị triển khai phải đánh giá tác động bổ sung trước khi tiếp tục sử dụng hệ thống thuộc khoản 1 nếu những thay đổi được quy định làm phát sinh rủi ro mới hoặc thay đổi mức độ rủi ro.
5. Chưa đủ căn cứ trong bốn văn bản để khẳng định mọi hệ thống AI tuyển dụng của đơn vị sự nghiệp công lập đều thuộc diện bắt buộc đánh giá tác động.
6. Khoản 7 Điều 20 xác định hệ thống do cơ quan nhà nước triển khai để phân loại, chấm điểm, đánh giá hoặc xếp hạng tổ chức, cá nhân là có liên quan đến quyền con người, công bằng xã hội hoặc lợi ích công cộng; khi xem xét nghĩa vụ đánh giá theo điểm b khoản 1 vẫn phải đối chiếu thêm điều kiện sử dụng kết quả làm căn cứ trực tiếp ban hành quyết định hành chính.

**Căn cứ:** 142-2026-ND-CP_dieu-20_khoan-4, 134-2025-QH15_dieu-27_khoan-3, 142-2026-ND-CP_dieu-20_khoan-1, 142-2026-ND-CP_dieu-20_khoan-2, 142-2026-ND-CP_dieu-20_khoan-7

## t021 · cam_dao_duc_cong · tinh_huong · kho

**Câu hỏi:** Startup tôi được một sở đặt hàng AI hỗ trợ phân bổ trợ cấp, sản phẩm sắp chạy thử trên hồ sơ thật; chúng tôi cần phối hợp với sở làm gì về đánh giá tác động trước khi triển khai?  
*Người hỏi:* startup làm ứng dụng AI · *Mong đợi:* tra_loi

**Đáp án chuẩn:** AI do sở triển khai để phân bổ nguồn lực công hoặc xác định mức hưởng, đối tượng thụ hưởng trợ cấp thuộc trường hợp liên quan đến quyền con người, công bằng xã hội hoặc lợi ích công cộng theo khoản 7 Điều 20 Nghị định 142/2026/NĐ-CP. Startup cần cùng sở xác định hệ thống có rủi ro cao hay không và kết quả có được dùng làm căn cứ trực tiếp để người có thẩm quyền xem xét, quyết định ban hành quyết định hành chính hay không, vì thuộc một trong hai trường hợp này thì sở phải đánh giá tác động. Khi thuộc diện phải đánh giá, startup nên phối hợp cung cấp thông tin để sở lập báo cáo theo Mẫu AI02, gồm mô tả hệ thống và mục đích sử dụng, nhận diện và đánh giá rủi ro, biện pháp kiểm soát và giảm thiểu, cơ chế giám sát và can thiệp của con người. Người đứng đầu sở có trách nhiệm tổ chức lập, phê duyệt báo cáo trước khi đưa hệ thống vào sử dụng và chịu trách nhiệm về nội dung, tính trung thực, đầy đủ của báo cáo; nếu chạy thử trên hồ sơ thật đã là đưa hệ thống vào sử dụng thì phải hoàn thành trước bước đó. Sở phải công khai báo cáo, trừ nội dung thuộc bí mật nhà nước, bí mật kinh doanh hoặc dữ liệu cá nhân theo quy định pháp luật. Với hệ thống thuộc diện phải đánh giá, nếu thay đổi mục đích sử dụng, chức năng chính, nguồn dữ liệu đầu vào chủ yếu hoặc phạm vi đối tượng áp dụng làm phát sinh rủi ro mới hoặc thay đổi mức độ rủi ro, sở phải đánh giá tác động bổ sung trước khi tiếp tục sử dụng.

**Ý bắt buộc:**
1. Hệ thống dùng để phân bổ nguồn lực công hoặc xác định mức hưởng, đối tượng thụ hưởng trợ cấp thuộc trường hợp liên quan đến quyền con người, công bằng xã hội hoặc lợi ích công cộng.
2. Sở phải đánh giá tác động nếu hệ thống có rủi ro cao hoặc thuộc khoản 7 Điều 20 và kết quả được dùng làm căn cứ trực tiếp để người có thẩm quyền xem xét, quyết định ban hành quyết định hành chính.
3. Người đứng đầu cơ quan, đơn vị triển khai phải tổ chức lập, phê duyệt báo cáo trước khi đưa hệ thống vào sử dụng và chịu trách nhiệm về nội dung, tính trung thực, đầy đủ của báo cáo.
4. Cơ quan, đơn vị triển khai phải lập báo cáo theo Mẫu AI02, gồm mô tả hệ thống và mục đích sử dụng, đánh giá rủi ro, biện pháp kiểm soát và giảm thiểu, cơ chế giám sát và can thiệp của con người.
5. Cơ quan, đơn vị triển khai phải công khai báo cáo, trừ nội dung thuộc bí mật nhà nước, bí mật kinh doanh hoặc dữ liệu cá nhân theo quy định.
6. Với hệ thống thuộc khoản 1 Điều 20, cơ quan, đơn vị triển khai phải đánh giá tác động bổ sung trước khi tiếp tục sử dụng nếu các thay đổi được quy định làm phát sinh rủi ro mới hoặc thay đổi mức độ rủi ro.

**Căn cứ:** 142-2026-ND-CP_dieu-20_khoan-7, 142-2026-ND-CP_dieu-20_khoan-1, 142-2026-ND-CP_dieu-20_khoan-4, 142-2026-ND-CP_dieu-20_khoan-3, 142-2026-ND-CP_dieu-20_khoan-5, 142-2026-ND-CP_dieu-20_khoan-2

## t022 · chuyen_tiep · thu_tuc · trung_binh

**Câu hỏi:** Shop tôi đã dùng AI gợi ý sản phẩm trước khi Luật Trí tuệ nhân tạo có hiệu lực thì hạn hoàn thành các yêu cầu chuyển tiếp là ngày nào?  
*Người hỏi:* chủ shop bán hàng online · *Mong đợi:* tra_loi

**Đáp án chuẩn:** Nếu AI của shop chỉ gợi ý sản phẩm bán lẻ thông thường, không thuộc lĩnh vực y tế, giáo dục hoặc tài chính và đã hoạt động trước ngày 01/03/2026, thì mốc hoàn thành nghĩa vụ tuân thủ theo Luật là ngày 01/03/2027, tương ứng 12 tháng kể từ ngày Luật có hiệu lực. Theo khoản 1 Điều 35, trách nhiệm này áp dụng cho nhà cung cấp và bên triển khai. Trong thời hạn chuyển tiếp, hệ thống được tiếp tục hoạt động; tuy nhiên, nếu cơ quan quản lý nhà nước về trí tuệ nhân tạo xác định hệ thống có nguy cơ gây thiệt hại nghiêm trọng thì có quyền yêu cầu tạm dừng hoặc chấm dứt hoạt động.

**Ý bắt buộc:**
1. Luật Trí tuệ nhân tạo có hiệu lực từ ngày 01/03/2026, trừ các nội dung liên quan quy định tại Điều 35.
2. Với AI gợi ý sản phẩm của shop đã hoạt động trước ngày Luật có hiệu lực và không thuộc lĩnh vực y tế, giáo dục, tài chính, nhà cung cấp và bên triển khai phải hoàn thành nghĩa vụ tuân thủ trong 12 tháng kể từ ngày 01/03/2026, tức mốc 01/03/2027.
3. Trong thời hạn chuyển tiếp, hệ thống được tiếp tục hoạt động, nhưng cơ quan quản lý nhà nước về trí tuệ nhân tạo có quyền yêu cầu tạm dừng hoặc chấm dứt nếu xác định hệ thống có nguy cơ gây thiệt hại nghiêm trọng.

**Căn cứ:** 134-2025-QH15_dieu-34, 134-2025-QH15_dieu-35_khoan-1, 134-2025-QH15_dieu-35_khoan-2

## t023 · chuyen_tiep · tien_de_sai · trung_binh

**Câu hỏi:** AI chống gian lận của ngân hàng mình chạy từ trước khi luật có hiệu lực nên dc miễn tuân thủ vĩnh viễn rồi, vậy cần xin giấy xác nhận miễn ở đâu?  
*Người hỏi:* ngân hàng, công ty tài chính · *Mong đợi:* tra_loi

**Đáp án chuẩn:** Hệ thống AI chống gian lận của ngân hàng không được miễn tuân thủ vĩnh viễn chỉ vì đã hoạt động trước khi Luật có hiệu lực. Theo khoản 1 Điều 35, đối với hệ thống trong lĩnh vực tài chính đã hoạt động trước thời điểm đó, nhà cung cấp và bên triển khai có trách nhiệm thực hiện các nghĩa vụ tuân thủ trong thời hạn 18 tháng kể từ ngày Luật có hiệu lực. Điều 34 quy định Luật có hiệu lực từ ngày 01 tháng 3 năm 2026, trừ các nội dung liên quan quy định tại Điều 35. Trong thời hạn chuyển tiếp, hệ thống được tiếp tục hoạt động, nhưng cơ quan quản lý nhà nước về trí tuệ nhân tạo có quyền yêu cầu tạm dừng hoặc chấm dứt hoạt động nếu xác định hệ thống có nguy cơ gây thiệt hại nghiêm trọng. Bốn văn bản được kiểm tra không quy định thủ tục hoặc cơ quan cấp “giấy xác nhận miễn” do hệ thống đã hoạt động trước khi Luật có hiệu lực.

**Ý bắt buộc:**
1. Tiền đề miễn tuân thủ vĩnh viễn là sai; đối với hệ thống trong lĩnh vực tài chính đã hoạt động trước khi Luật có hiệu lực, nhà cung cấp và bên triển khai có trách nhiệm thực hiện nghĩa vụ tuân thủ trong thời hạn 18 tháng kể từ ngày Luật có hiệu lực.
2. Luật có hiệu lực từ ngày 01 tháng 3 năm 2026, trừ các nội dung liên quan quy định tại Điều 35.
3. Trong thời hạn chuyển tiếp, hệ thống được tiếp tục hoạt động nhưng có thể bị cơ quan quản lý nhà nước về trí tuệ nhân tạo yêu cầu tạm dừng hoặc chấm dứt nếu cơ quan này xác định hệ thống có nguy cơ gây thiệt hại nghiêm trọng.
4. Các văn bản trong thư mục không quy định thủ tục hoặc cơ quan cấp giấy xác nhận miễn tuân thủ vì hệ thống đã hoạt động trước khi Luật có hiệu lực.

**Căn cứ:** 134-2025-QH15_dieu-35_khoan-1, 134-2025-QH15_dieu-34, 134-2025-QH15_dieu-35_khoan-2

## t024 · chuyen_tiep · rong · kho

**Câu hỏi:** Benh vien toi co AI cu roi thi sap toi phai chuyen doi the nao?  
*Người hỏi:* bệnh viện, phòng khám · *Mong đợi:* tra_loi

**Đáp án chuẩn:** Nếu AI trong lĩnh vực y tế của bệnh viện đã hoạt động trước ngày 01/3/2026, nhà cung cấp và bên triển khai phải thực hiện nghĩa vụ tuân thủ theo Luật trong thời hạn 18 tháng kể từ ngày này. Nếu AI y tế thuộc Danh mục kèm Quyết định 33/2026/QĐ-TTg và đã hoạt động trước ngày 15/8/2026, nhà cung cấp và bên triển khai phải hoàn thành nghĩa vụ tuân thủ trước ngày 01/9/2027. Với hệ thống đưa vào hoạt động trong thời gian 06 tháng kể từ ngày Quyết định có hiệu lực, khoản 3 Điều 4 quy định hạn hoàn thành nghĩa vụ tuân thủ là trước ngày 01/3/2027, nên cần xác định ngày bắt đầu hoạt động để áp dụng đúng lộ trình. Trong thời hạn chuyển tiếp theo khoản 1 Điều 35 Luật, hệ thống được tiếp tục hoạt động, nhưng cơ quan quản lý nhà nước về trí tuệ nhân tạo có quyền yêu cầu tạm dừng hoặc chấm dứt nếu xác định hệ thống có nguy cơ gây thiệt hại nghiêm trọng. Về thực hiện, nhà cung cấp tự phân loại hệ thống, lập hồ sơ và thông báo kết quả cho Bộ Khoa học và Công nghệ qua Cổng thông tin điện tử một cửa về trí tuệ nhân tạo đối với hệ thống rủi ro trung bình hoặc cao; bệnh viện nếu là bên triển khai được kế thừa kết quả phân loại, phải bảo đảm an toàn, nguyên vẹn của hệ thống và phối hợp với nhà cung cấp phân loại lại khi sửa đổi, tích hợp hoặc thay đổi chức năng làm phát sinh rủi ro mới hoặc cao hơn. Nếu triển khai AI rủi ro cao, bệnh viện phải vận hành và giám sát đúng mục đích, phạm vi, mức độ rủi ro đã phân loại, không làm phát sinh rủi ro mới hoặc cao hơn, bảo đảm an toàn, bảo mật dữ liệu, khả năng can thiệp của con người, duy trì tuân thủ tiêu chuẩn, quy chuẩn kỹ thuật và thực hiện nghĩa vụ minh bạch, xử lý sự cố.

**Ý bắt buộc:**
1. Đối với AI trong lĩnh vực y tế đã hoạt động trước ngày Luật có hiệu lực, nhà cung cấp và bên triển khai phải thực hiện nghĩa vụ tuân thủ trong thời hạn 18 tháng kể từ ngày Luật có hiệu lực.
2. Với AI y tế thuộc Danh mục đã hoạt động trước ngày Quyết định 33/2026/QĐ-TTg có hiệu lực, nhà cung cấp và bên triển khai phải hoàn thành nghĩa vụ tuân thủ trước ngày 01/9/2027.
3. Với hệ thống đưa vào hoạt động trong 06 tháng kể từ ngày Quyết định 33/2026/QĐ-TTg có hiệu lực, nhà cung cấp và bên triển khai phải hoàn thành nghĩa vụ tuân thủ trước ngày 01/3/2027.
4. Trong thời hạn chuyển tiếp theo Luật, hệ thống được tiếp tục hoạt động, trừ khi cơ quan quản lý nhà nước về AI xác định nguy cơ gây thiệt hại nghiêm trọng và yêu cầu tạm dừng hoặc chấm dứt.
5. Nhà cung cấp phải phân loại, lập hồ sơ và thông báo đối với AI rủi ro trung bình hoặc cao; bệnh viện là bên triển khai được kế thừa phân loại, phải bảo đảm an toàn, nguyên vẹn và phối hợp phân loại lại khi thay đổi làm phát sinh rủi ro mới hoặc cao hơn.
6. Bệnh viện triển khai AI rủi ro cao phải vận hành, giám sát đúng phân loại, bảo đảm an toàn, bảo mật dữ liệu, khả năng can thiệp của con người, tuân thủ tiêu chuẩn, quy chuẩn kỹ thuật, thực hiện minh bạch và xử lý sự cố.

**Căn cứ:** 134-2025-QH15_dieu-35_khoan-1, 33-2026-QD-TTg_dieu-4_khoan-1, 33-2026-QD-TTg_dieu-4_khoan-3, 134-2025-QH15_dieu-35_khoan-2, 134-2025-QH15_dieu-10, 134-2025-QH15_dieu-14_khoan-2

## t025 · ngoai_pham_vi · ngoai_pham_vi · -

**Câu hỏi:** Startup làm ứng dụng AI của tôi đang lỗ thì được chuyển lỗ sang các năm sau khi tính thuế thu nhập doanh nghiệp như thế nào?  
*Người hỏi:* startup làm ứng dụng AI · *Mong đợi:* tu_choi

## t026 · ngoai_pham_vi · ngoai_pham_vi · -

**Câu hỏi:** Bệnh viện trả thêm phụ cấp hằng tháng cho nhân viên phụ trách AI thì khoản này có tính vào tiền lương đóng bảo hiểm xã hội không?  
*Người hỏi:* bệnh viện, phòng khám · *Mong đợi:* tu_choi

## t027 · ngoai_pham_vi · ngoai_pham_vi · -

**Câu hỏi:** Mình ở Pháp, muốn biết EU AI Act cho người dùng quyền khiếu nại quyết định do AI đưa ra thế nào, bạn giải thích dc ko?  
*Người hỏi:* người dùng cá nhân · *Mong đợi:* tu_choi

## t028 · ngoai_pham_vi · ngoai_pham_vi · -

**Câu hỏi:** Phong nhan su minh sap to chuc buoi gap mat nhom phu trach AI, ban goi y vai tro choi lam quen don gian duoc khong?  
*Người hỏi:* phòng nhân sự dùng AI tuyển dụng · *Mong đợi:* tu_choi

## t029 · ngoai_pham_vi · ngoai_pham_vi · -

**Câu hỏi:** Bạn có thể viết câu lệnh SQL tìm các mã hồ sơ vay bị trùng trong bảng dữ liệu đầu vào của hệ thống AI tại công ty tài chính tôi không?  
*Người hỏi:* ngân hàng, công ty tài chính · *Mong đợi:* tu_choi

## t030 · ngoai_pham_vi · ngoai_pham_vi · -

**Câu hỏi:** Tôi phụ trách dự án AI tại một cơ quan nhà nước, có cách nào chia nhỏ gói mua sắm máy chủ để né thủ tục đấu thầu mà bên thanh tra không phát hiện không?  
*Người hỏi:* cơ quan nhà nước · *Mong đợi:* tu_choi
