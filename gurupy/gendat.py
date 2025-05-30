"""
guru.py 用データファイル作成

原作: X68000 マシン語プログラミング (Oh!X 1992 年 8 月号)
"""

import x68k
import math
from binascii import unhexlify
from struct import pack
from sys import exit

# if __name__ != "__main__":
#     print("This is not intended to be imported as a module.")
#     exit(1)


def generate_spdat(output_file: str):
    """
    spdat.bin ファイルを生成する関数

    計算誤差のせいか、 SPDAT.BAS の実行結果とは微妙に異なる

    @param output_file 出力するファイル名
    @return 成功した場合は True、失敗した場合は False
    """
    print(f"{output_file} を生成しています ... ", end="")

    spdat = []
    for i in range(512):
        x = int(256 + 160 * math.cos(math.pi * i / 256) + 16)
        y = int(256 + 160 * math.sin(math.pi * i / 256) * 4 / 3 + 16)
        spdat.append(pack("HH", x, y))

    for i in range(512):
        spdat.append(spdat[i])  # 後半は前半をコピーする

    try:
        with open(output_file, "wb") as f:
            f.write(b"".join(spdat))
        print("OK")
        return True
    except IOError as e:
        print(f"エラー : {e}")
        return False


def generate_bgdat(output_file: str, gvram: GVRam, s: str) -> bool:
    """
    bgdat.bin ファイルを生成する関数

    グラフィック画面に文字を描画し、そのビットマップデータをバイナリファイルとして保存する

    @param output_file 出力するファイル名
    @param gvram GVRam オブジェクト
    @param s 描画する文字列
    @return 成功した場合は True、失敗した場合は False
    """
    print(f"{output_file} を生成しています ... ", end="")

    gvram.symbol(0, 4, s, 1, 1, 1, 2, 0)

    n = len(unhexlify(s.encode("sjis").hex()))
    bgdat = []

    for x in range(n * 12):
        for y in range(32):
            bgdat.append(pack("H", 256 + gvram.point(x, y)))

    try:
        with open(output_file, "wb") as f:
            f.write(b"".join(bgdat))
        print("OK")
        return True
    except IOError as e:
        print(f"エラー : {e}")
        return False


if x68k.iocs(x68k.i.TGUSEMD, 0, -1) != 0:
    print("グラフィック画面が使用中です。中断します")
    exit(1)


x68k.crtmod(0, True)
x68k.vpage(1)  # ページ 0 のみ表示
g = x68k.GVRam(0)
generate_bgdat("bgdat.bin", g, "魑魅魍魎")

generate_spdat("spdat.bin")

exit(0)
