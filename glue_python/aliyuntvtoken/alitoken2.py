#!/usr/local/bin/python3
# pylint: disable=C0114
# pylint: disable=C0116
# pylint: disable=C0103

import time
import os
import logging
import json
import uuid
import hashlib
import base64
import random
import argparse
import sys

import requests
import qrcode
from flask import Flask, jsonify, render_template, request
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad


logging.basicConfig(level=logging.INFO)
app = Flask(__name__)


class AliyunPanTvToken:
    """
    阿里云盘 TV Token 解密刷新模块
    """

    def __init__(self):
        self.timestamp = str(requests.get("http://api.extscreen.com/timestamp", timeout=10).json()["data"]["timestamp"])
        self.unique_id = uuid.uuid4().hex
        self.wifimac = str(random.randint(10**11, 10**12 - 1))
        self.headers = {
            "token": "6733b42e28cdba32",
            "User-Agent": "Mozilla/5.0 (Linux; U; Android 9; zh-cn; SM-S908E Build/TP1A.220624.014) AppleWebKit/533.1 (KHTML, like Gecko) Mobile Safari/533.1",  # noqa: E501
            "Host": "api.extscreen.com",
        }

    def h(self, char_array, modifier):
        unique_chars = list(dict.fromkeys(char_array))
        numeric_modifier = int(modifier[7:])
        transformed_string = "".join(
            [
                chr(
                    abs(ord(c) - (numeric_modifier % 127) - 1) + 33
                    if abs(ord(c) - (numeric_modifier % 127) - 1) < 33
                    # noqa: E501
                    else abs(ord(c) - (numeric_modifier % 127) - 1)
                )
                for c in unique_chars
            ]
        )
        return transformed_string

    def get_params(self):
        params = {
            "akv": "2.8.1496",
            "apv": "1.3.8",
            "b": "samsung",
            "d": self.unique_id,
            "m": "SM-S908E",
            "mac": "",
            "n": "SM-S908E",
            "t": self.timestamp,
            "wifiMac": self.wifimac,
        }
        return params

    def generate_key(self):
        params = self.get_params()
        sorted_keys = sorted(params.keys())
        concatenated_params = "".join([params[key] for key in sorted_keys if key != "t"])
        hashed_key = self.h(list(concatenated_params), self.timestamp)
        return hashlib.md5(hashed_key.encode("utf-8")).hexdigest()

    def decrypt(self, ciphertext, iv):
        try:
            key = self.generate_key()
            cipher = AES.new(key.encode("utf-8"), AES.MODE_CBC, iv=bytes.fromhex(iv))
            decrypted = unpad(cipher.decrypt(base64.b64decode(ciphertext)), AES.block_size)
            dec = decrypted.decode("utf-8")
            return dec
        except Exception as error:
            logging.error("Decryption failed %s", error)
            raise error

    def get_headers(self):
        return {**self.get_params(), **self.headers}

    def get_token(self, data):
        token_data = requests.post(
            "http://api.extscreen.com/aliyundrive/v3/token", data=data, headers=self.get_headers(), timeout=10
        ).json()["data"]
        return self.decrypt(token_data["ciphertext"], token_data["iv"])

    def get_qrcode_url(self):
        data = requests.post(
                "http://api.extscreen.com/aliyundrive/qrcode",
                data={
                    "scopes": ",".join(["user:base", "file:all:read", "file:all:write"]),
                    "width": 500,
                    "height": 500,
                },
                headers=self.get_headers(),
                timeout=10,
            ).json()["data"]
        qr_link = "https://www.aliyundrive.com/o/oauth/authorize?sid=" + data["sid"]
        return {"qr_link": qr_link, "sid": data["sid"]}


def check_qrcode_status(sid):
    status = "NotLoggedIn"
    _auth_code = None
    while status != "LoginSuccess":
        time.sleep(3)
        result = requests.get(f"https://openapi.alipan.com/oauth/qrcode/{sid}/status", timeout=10).json()
        status = result["status"]
        if status == "LoginSuccess":
            _auth_code = result["authCode"]
    return {"auth_code": _auth_code}


def get_token(code):
    data = { "code": code }
    token_data = CLIENT.get_token(data)
    parsed_json = json.loads(token_data)
    refresh_token = parsed_json["refresh_token"]
    if sys.platform.startswith("win32"):
        file_path = ""
    else:
        file_path = "/data/"
    with open(f"{file_path}myopentoken.txt", "w", encoding="utf-8") as file:
        file.write(refresh_token)
    logging.info("myopentoken.txt 文件更新成功！")
    with open(f"{file_path}open_tv_token_url.txt", "w", encoding="utf-8") as file:
        file.write("https://alipan-tv-token.pages.dev/refresh")
    logging.info("open_tv_token_url.txt 文件更新成功！")


@app.route("/")
def main_page():
    return render_template("qrcode.html")


@app.route("/get_qrcode", methods=["GET"])
def get_qrcode():
    return jsonify(CLIENT.get_qrcode_url())


@app.route("/check_qrcode/<sid>", methods=["GET"])
def check_qrcode(sid):
    return jsonify(check_qrcode_status(sid))


@app.route("/get_tokens", methods=["POST"])
def get_tokens():
    _auth_code = request.json.get("auth_code")
    get_token(_auth_code)
    return jsonify({"status": "completed"})


@app.route("/shutdown_server", methods=["GET"])
def shutdown():
    os._exit(0)


CLIENT = AliyunPanTvToken()
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AliyunPan TV Token")
    parser.add_argument("--qrcode_mode", type=str, required=True, help="扫码模式")
    args = parser.parse_args()
    if args.qrcode_mode == "web":
        app.run(host="0.0.0.0", port=34256)
    elif args.qrcode_mode == "shell":
        date = CLIENT.get_qrcode_url()
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=5, border=4)
        qr.add_data(date["qr_link"])
        qr.make(fit=True)
        logging.info("请打开阿里云盘扫描此二维码！")
        qr.print_ascii(invert=True, tty=sys.stdout.isatty())
        auth_code = check_qrcode_status(date["sid"])["auth_code"]
        get_token(auth_code)
    else:
        logging.error("未知的扫码模式")
        os._exit(1)
