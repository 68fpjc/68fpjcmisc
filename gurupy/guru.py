"""
スプライトと BG のデモ

原作 : X68000 マシン語プログラミング (Oh!X 1992 年 8 月号)
"""

import x68k
from binascii import unhexlify
from struct import pack
from sys import exit, argv
import uctypes
import micropython

# if __name__ != "__main__":
#     print("This is not intended to be imported as a module.")
#     exit(1)

NMAXSP = const(128)  # スプライトの最大数

SPSCRLREG = const(0xEB0000)  # スプライトスクロールレジスタ
BGSCRLREG0 = const(0xEB0800)  # BG スクロールレジスタ 0
BGCTRLREG = const(0xEB0808)  # BG コントロールレジスタ
BGDATAAREA1 = const(0xEBE000)  # BG の BG データエリア 1

WORD = const(2)  # ワードサイズ


def setup_global_state(
    opt_num_sp: int, opt_use_asm_int: bool, opt_use_asm_move: bool, opt_invert_bg: bool
):
    """
    変数を初期化する。仕方なくグローバル変数で

    - インスタンス変数等にするとアクセスが非常に重い
    - 関数のローカル変数にするとバイパーモードでのアクセスが面倒

    @param opt_num_sp スプライトの数
    @param opt_use_asm_int 描画処理でインラインアセンブラを使用する場合は True
    @param opt_use_asm_move 移動処理でインラインアセンブラを使用する場合は True
    @param opt_invert_bg マップデータを反転する場合は True
    """

    @micropython.viper
    def invert_bgdat():
        """
        マップデータを反転する
        """
        p = ptr16(bgdat)
        for i in range(int(bgdat_idx_max)):
            p[i] ^= 0x0001

    global spreg, spdat, bgdat, sp_offset0, sp_offset, num_sp
    global bgdat_idx_max, bgx, bgctr, bgsour_idx, bgdest_idx
    global use_asm_int, use_asm_move
    try:
        spdat = load_binary_file("spdat.bin")  # スプライト座標データ
        bgdat = load_binary_file("bgdat.bin")  # マップデータ
    except OSError as e:
        print(f"Error: {e}")
        exit(1)

    spreg = create_spreg(opt_num_sp)  # 仮想スプライトスクロールレジスタ
    sp_offset0 = len(spdat) // 2 // WORD // 2  # スプライト座標データのオフセット初期値
    sp_offset = sp_offset0  # スプライト座標データのオフセット

    bgdat_idx_max = len(bgdat) // WORD  # マップデータの最大インデックス (ワード単位)
    bgx = 0  # BG の X 表示座標
    bgctr = 0  # BG 更新用カウンタ (0 〜 15)
    bgsour_idx = 0  # マップデータのインデックス (0 〜 bgdat_idx_max - 1)
    bgdest_idx = 32  # BG データエリアのインデックス (0 〜 63)
    num_sp = opt_num_sp  # スプライトの数
    use_asm_int = opt_use_asm_int  # 描画処理でインラインアセンブラを使用するか
    use_asm_move = opt_use_asm_move  # 移動処理でインラインアセンブラを使用するか
    if opt_invert_bg:
        invert_bgdat()


@micropython.viper
def vsync_and_render():
    """
    垂直帰線期間を待ち、スプライトと BG の表示を行う
    """
    x68k.vsync()  # 垂直帰線期間を待つ

    bgctrlreg = ptr16(BGCTRLREG)
    bgctrlreg[0] = 0x0000  # スプライト / BG の表示をオフにする

    # スプライト

    # 仮想スプライトスクロールレジスタから
    # (実) スプライトスクロールレジスタへブロック転送する
    if use_asm_int:
        render_asm_sp(spreg, num_sp)
    else:
        sp = ptr16(spreg)
        dp = ptr16(SPSCRLREG)
        for i in range(0, int(num_sp) * 4, 4):
            dp[i + 0] = sp[i + 0]  # X 座標
            dp[i + 1] = sp[i + 1]  # Y 座標
            dp[i + 2] = sp[i + 2]  # 属性 1
            dp[i + 3] = sp[i + 3]  # 属性 2

    # BG

    # BG の表示 X 座標を更新する
    # (1 ワードの更新なのでインラインアセンブラを使うまでもない？)
    dp = ptr16(BGSCRLREG0)
    dp[0] = int(bgx)  # BG の表示 X 座標を更新する

    # 16 回スクロールしたら BG を書き直す
    if not bgctr:
        if use_asm_int:
            # インラインアセンブラには 5 つ以上の引数を渡せないようだ
            render_asm_bg(bgdat, bgsour_idx, bgdest_idx)
        else:
            sp = ptr16(bgdat)
            dp = ptr16(BGDATAAREA1)
            i = int(bgdest_idx)
            j = int(bgsour_idx)
            for k in range(32):  # 32 キャラクタ分転送する
                dp[i] = sp[j + k]
                i += 64

    bgctrlreg[0] = 0x0203  # スプライト / BG の表示をオンにする


@micropython.asm_m68k
def render_asm_sp(spreg: bytes, num_sp: int):
    """
    スプライトの表示を行うアセンブラ実装

    @param spreg 仮想スプライトスクロールレジスタ
    @param num_sp スプライトの数 (下位 16 ビットのみ使用)
    """
    moveal(fp[8], a0)  # spreg
    lea([0xEB0000], a1)
    movew(fp[12 + 2], d0)  # num_sp
    subqw(1, d0)
    label(cpylp)
    movel([a0.inc], [a1.inc])
    movel([a0.inc], [a1.inc])
    dbra(d0, cpylp)


@micropython.asm_m68k
def render_asm_bg(bgdat: bytes, bgsour_idx: int, bgdest_idx: int):
    """
    BG の表示を行うアセンブラ実装

    @param bgdat マップデータ
    @param bgsour_idx マップデータのインデックス (下位 16 ビットのみ使用)
    @param bgdest_idx BG データエリアのインデックス (下位 16 ビットのみ使用)
    """
    moveal(fp[8], a0)
    movew(fp[12 + 2], d0)
    addw(d0, d0)
    addaw(d0, a0)
    lea([0xEBE000], a1)
    movew(fp[16 + 2], d0)
    addw(d0, d0)
    addaw(d0, a1)
    moveq(32 - 1, d0)  # 32 キャラクタ分転送する
    label(bglp)
    movew([a0.inc], [a1])
    lea([64 * 2, a1], a1)
    dbra(d0, bglp)


@micropython.viper
def move():
    """
    スプライトと BG の移動処理を行う
    """
    # スプライト
    global sp_offset
    v = int(sp_offset) - 1
    if v < 0:
        v = int(sp_offset0)  # 座標データのオフセットをリセットする
    sp_offset = v

    # BG
    global bgx, bgctr, bgsour_idx, bgdest_idx
    bgx = int(bgx) + 1  # BG の表示 X 座標を更新する
    v = int(bgctr)
    bgctr = (v + 1) & 0x0F  # BG 更新用カウンタを更新する
    if v == 0:
        v = int(bgsour_idx) + 32  # 縦 32 キャラクタ分進める
        if v >= int(bgdat_idx_max):
            v = 0
        bgsour_idx = v

        v = int(bgdest_idx) + 1
        if v >= 64:
            v = 0
        bgdest_idx = v

    update_spbuf()  # 仮想スプライトスクロールレジスタを更新する


@micropython.viper
def move_first():
    """
    スプライトと BG の移動処理を行う (初回)
    """

    update_spbuf()  # 仮想スプライトスクロールレジスタを更新する


@micropython.viper
def update_spbuf():
    """
    仮想スプライトスクロールレジスタを更新する
    """
    # スプライト
    v = int(sp_offset)
    if use_asm_move:
        update_spbuf_asm(spdat, spreg, v, num_sp)
    else:
        spdat_ptr = ptr16(spdat)
        spreg_ptr = ptr16(spreg)
        i = 0
        for j in range(0, int(num_sp) * 4, 4):
            idx = (v + i * 3) * 2
            spreg_ptr[j + 0] = spdat_ptr[idx + 0]  # X 座標
            spreg_ptr[j + 1] = spdat_ptr[idx + 1]  # Y 座標
            i += 1


@micropython.asm_m68k
def update_spbuf_asm(
    spdat_buf: bytes, spreg_buf: bytearray, sp_offset: int, num_sp: int
):
    """
    仮想スプライトスクロールレジスタを更新するアセンブラ実装

    @param spdat_buf スプライト座標データ
    @param spreg_buf 仮想スプライトスクロールレジスタ
    @param sp_offset オフセット値 (下位 16 ビットのみ使用)
    @param num_sp スプライトの数 (下位 16 ビットのみ使用)
    """
    moveal(fp[8], a0)  # spdat
    moveal(fp[12], a1)  # spreg
    movew(fp[16 + 2], d0)  # sp_offset
    addw(d0, d0)
    addw(d0, d0)
    addaw(d0, a0)
    movew(fp[20 + 2], d1)  # num_sp
    subqw(1, d1)
    label(setlp)
    movel([a0.inc], [a1.inc])
    addqw(8, a0)
    addqw(4, a1)
    dbra(d1, setlp)


def load_binary_file(filename: str) -> bytes:
    """
    バイナリファイルを読み込む

    @param filename 読み込むファイル名
    @return 読み込んだバイナリデータ
    @exception OSError ファイルの読み込みに失敗した場合
    """
    if __debug__:
        print(f"Loading {filename} ... ", end="")
    try:
        with open(filename, "rb") as f:
            data = f.read()
            if __debug__:
                print("OK")
            return data
    except OSError as e:
        raise OSError(f"Cannot load file '{filename}': {e}")


def create_spreg(num_sp: int) -> bytearray:
    """
    仮想スプライトスクロールレジスタを作成する
    """
    spreg = bytearray()  # 仮想スプライトスクロールレジスタ
    for _ in range(num_sp):  # 仮想スプライトスクロールレジスタを初期化する
        spreg.extend(pack("4H", 0x0000, 0x0000, 0x0101, 0x0003))
    return spreg


def setup_sprite(s: Sprite):
    """
    スプライトハードウェアの初期設定を行う
    """
    s.init()  # スプライト初期化
    s.clr()
    s.disp()
    s.defcg(  # スプライトパターンをひとつ定義
        1,
        unhexlify(  # 適当なスプライトパターン
            (
                "dddddddd d3333333 d3333333 d3333333"
                "d3333333 d3333333 d3333333 d3333333"
                "d3333333 d3333333 d3333333 d3333333"
                "d3333333 d3333333 d3333333 dddddddd"
                "dddddddd 3333333d 3333333d 3333333d"
                "3333333d 3333333d 3333333d 3333333d"
                "3333333d 3333333d 3333333d 3333333d"
                "3333333d 3333333d 3333333d dddddddd"
            ).replace(" ", "")
        ),
        2,
    )


def parse_args(argv):
    """
    コマンドライン引数を解析する

    @param argv コマンドライン引数
    @return tuple (num_sp, use_asm_int, use_asm_move, invert_bg)
    """
    num_sp = NMAXSP  # スプライトの数 (デフォルトは 128)
    use_asm_int = True  # 描画処理でインラインアセンブラを使用する
    use_asm_move = True  # 移動処理でインラインアセンブラを使用する
    invert_bg = False  # マップデータを反転する
    for arg in argv:
        if arg.startswith("--sp="):
            try:
                v = int(arg.split("=")[1])
                if v >= 1 and v <= NMAXSP:
                    num_sp = v
            except (ValueError, IndexError):
                pass
        elif arg == "--no-asm-int":
            use_asm_int = False
        elif arg == "--no-asm-move":
            use_asm_move = False
        elif arg == "--invert-bg":
            invert_bg = True
    return num_sp, use_asm_int, use_asm_move, invert_bg


@micropython.viper
def mainloop():
    """
    メインループ
    """
    with x68k.Super():
        move_first()  # 初回
        while True:
            # キーが押されたら終了する
            if (int(x68k.iocs(x68k.i.B_KEYSNS)) & 0xFFFF) and (
                int(x68k.iocs(x68k.i.B_KEYINP)) & 0xFF
            ):
                break
            vsync_and_render()  # スプライトと BG の表示を行う
            move()  # スプライトと BG の移動処理を行う


def main():
    """
    メイン関数
    """

    micropython.alloc_emergency_exception_buf(100)

    x68k.curoff()  # カーソル非表示
    x68k.crtmod(0)  # 512x512, 16 色 4 画面, 高解像度
    s = x68k.Sprite()
    setup_sprite(s)  # スプライトハードウェアの初期設定を行う

    # コマンドライン引数を解析する
    opt_num_sp, opt_use_asm_int, opt_use_asm_move, opt_invert_bg = parse_args(argv)

    setup_global_state(  # グローバル変数を初期化する
        opt_num_sp, opt_use_asm_int, opt_use_asm_move, opt_invert_bg
    )

    # デバッグ情報
    if __debug__:
        print("spdat:", hex(uctypes.addressof(spdat)))
        print("bgdat:", hex(uctypes.addressof(bgdat)))
        print("spreg:", hex(uctypes.addressof(spreg)))

    mainloop()

    s.disp(False)  # スプライト非表示
    x68k.curon()  # カーソル表示
    exit(0)


main()
