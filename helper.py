import requests
import time
import argparse
import os
import re
import subprocess
import tempfile


botUrl = "http://192.168.31.135"
botPort = 3000
token = "114514"
headers = {"Authorization": f"Bearer {token}"}
last_real_req = 0
last_message_seq = 1430240835
source_group_id = "1092143423"
napcat_rootfs = "/data/data/com.termux/files/usr/var/lib/proot-distro/installed-rootfs/napcat"


def sanitize_name(name):
    cleaned = re.sub(r"[\\/:*?\"<>|]", "_", name.strip())
    return cleaned or "Unknown"




def get_message(group_id):
    global last_message_seq
    payload = {
        "group_id": group_id,
        "count": 200,
        #"reverseOrder": True,
        "parse_mult_msg": True
    }
    if last_message_seq:
        payload["message_seq"] = last_message_seq
    response = requests.post(
        f"{botUrl}:{botPort}/get_group_msg_history",
        json=payload,
        headers=headers,
        timeout=10,
    )
    if response.status_code == 200:
        data = response.json()
        print(data)
        list =[message for message in data["data"]["messages"]]
        return list
    else:
        print(f"Error: {response.status_code}")
        return []

def check_new_message(messages):
    global last_real_req, last_message_seq
    message_queue = []
    if(len(messages) > 0):
        for message in messages:
            if int(message["real_seq"]) > last_real_req:
                message_queue.append(message)
        last_real_req = int(messages[-1]["real_seq"])
        last_message_seq = int(messages[-1]["message_seq"])+1
    return message_queue
def get_file_from_url(file_url,type):
    if type == "image":
        response = requests.get(file_url, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.content
        else:
            print(f"Error retrieving {type} from {file_url}: {response.status_code}")
            return None
    elif type == "file":
        if not file_url:
            print("Empty file path from get_file response")
            return None

        remote_path = str(file_url)
        local_path = os.path.join(napcat_rootfs, remote_path.lstrip("/"))
        # Prefer direct local read from napcat rootfs path.
        remote_host = botUrl.replace("http://", "").replace("https://", "").split(":", 1)[0]
        temp_fd, temp_path = tempfile.mkstemp()
        os.close(temp_fd)
        try:
            scp_cmd = [
                "scp",
                "-P",
                "8022",
                f"u0_a541@{remote_host}:{local_path}",
                temp_path,
            ]
            result = subprocess.run(scp_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                stderr = (result.stderr or "").strip()
                print(f"Error retrieving file via scp: {stderr}")
                return None

            with open(temp_path, "rb") as file_handle:
                return file_handle.read()
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
    

def get_message_file(messages):
    for message in messages:
        if message["real_seq"]=="341":
            print(f" {message}")
        msg = message.get("raw_message", "")
        user= message.get("sender", {}).get("card", "Unknown")
        print(msg)
        if msg.startswith("[CQ:forward"):
            response = requests.post(
                f"{botUrl}:{botPort}/get_forward_msg",
                json={"message_id": message.get("message_id")},
                headers=headers,
                timeout=10,
            )
            if response.status_code == 200:
                data = response.json()
                list =[message for message in data["data"]["messages"]]
                get_message_file(list)
            else:
                print(f"Error retrieving forward message: {response.status_code}")
        if (msg.startswith("[CQ:image") or msg.startswith("[CQ:file")) and "file=" in msg:
            msg_type = "image" if msg.startswith("[CQ:image") else "file"
            file_name = msg.split("file=", 1)[1].split(",", 1)[0]
            file_url_message = requests.post(
                f"{botUrl}:{botPort}/get_file",
                json={"file": file_name},
                headers=headers,
                timeout=10,
            )
            #print(f"Requested file URL for {file_name}, status code: {file_url_message.status_code}")
            if file_url_message.status_code == 200:
                data = file_url_message.json()
                response_data = data.get("data", {})
                if msg_type == "file":
                    file_ref = response_data.get("file") or response_data.get("url")
                    save_name = response_data.get("file_name") or file_name
                else:
                    file_ref = response_data.get("url")
                    save_name = file_name

                if not file_ref:
                    print(f"File reference not found in response for {file_name}: {data}")
                    continue
            else:
                print(f"Error retrieving file URL for {file_name}: {file_url_message.status_code}")
                continue
            try:
                file_content = get_file_from_url(file_ref, msg_type)
                if file_content:
                    user_dir = os.path.join("result", sanitize_name(user))
                    os.makedirs(user_dir, exist_ok=True)
                    file_path = os.path.join(user_dir, save_name)
                    with open(file_path, "wb") as file_handle:
                        file_handle.write(file_content)
                    print(f"Saved file to {file_path}")
            except Exception as e:
                print(f"Error retrieving file from {file_ref}: {e}")

def main():
    global token, botUrl, botPort, last_real_req, last_message_seq, headers, source_group_id
    # Refresh headers after loading runtime token.
    headers = {"Authorization": f"Bearer {token}"}
    while True: # 每5秒检查一次新消息
        try :
            messages = get_message(source_group_id)
        except Exception as e:
            print(f"Error getting messages: {e}")
            time.sleep(5)
            continue
        try:
            get_message_file(
            messages=check_new_message(messages))
        except Exception as e:
            print(f"send_message出错: {e}")
            time.sleep(5)
            continue
        print("Loop completed, sleeping for 5 seconds...")
        time.sleep(5) 

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Message forwarding helper")
    parser.add_argument(
        "--source-group-id",
        type=str,
        default="1092143423",
        help="Source group id for polling message history",
    )
    parser.add_argument(
        "--last-real-id",
        type=int,
        default=0,
        help="Initialize last_real_id before polling messages",
    )
    parser.add_argument(
        "--message-seq",
        type=str,
        default=None,
        help="Optional message_seq for get_group_msg_history (default: use last_real_id)",
    )
    args = parser.parse_args()
    source_group_id = args.source_group_id
    last_real_req = args.last_real_id
    if args.message_seq is not None:
        last_message_seq = int(args.message_seq)
    main()


# proot-distro sh napcat -- bash -c "xvfb-run -a /root/Napcat/opt/QQ/qq --no-sandbox"