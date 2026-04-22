import smtplib
import os
from email.message import EmailMessage

def send_docx():
    # 从 GitHub 的“保险箱”里读取信息
    sender_email = os.getenv("EMAIL_USER")
    sender_password = os.getenv("EMAIL_PASS")
    receiver_email = os.getenv("EMAIL_USER") # 发给自己
    
    # 找到生成的 docx 文件（假设你的 ai_processor 生成的文件名包含 .docx）
    docx_file = "un_internships.docx" 
    
    if not os.path.exists(docx_file):
        print("未找到结果文件，无法发送邮件。")
        return

    msg = EmailMessage()
    msg['Subject'] = "【自动提醒】联合国实习岗位更新报告"
    msg['From'] = sender_email
    msg['To'] = receiver_email
    msg.set_content("亲爱的 Tian Ran，本月最新的联合国实习筛选结果已附件，请查收。")

    with open(docx_file, 'rb') as f:
        file_data = f.read()
        msg.add_attachment(file_data, maintype='application', subtype='vnd.openxmlformats-officedocument.wordprocessingml.document', filename=docx_file)

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp: # 如果用网易云邮箱请改为 smtp.163.com
        smtp.login(sender_email, sender_password)
        smtp.send_message(msg)
    print("邮件发送成功！")

if __name__ == "__main__":
    send_docx()
