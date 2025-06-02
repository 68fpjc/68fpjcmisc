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


class GlobalState:
    """
    状態を管理するクラス
    """

    def __init__(self):
        self.spreg = None
        """仮想スプライトスクロールレジスタ"""
        self.spdat = None
        """スプライト座標データ"""
        self.bgdat = None
        """マップデータ"""
        self.sp_offset0 = 0
        """スプライト座標データのオフセット初期値"""
        self.sp_offset = 0
        """スプライト座標データのオフセット"""
        self.bgdat_idx_max = 0
        """マップデータの最大インデックス (ワード単位)"""
        self.bgx = 0
        """BG の X 表示座標"""
        self.bgctr = 0
        """BG 更新用カウンタ (0 〜 15)"""
        self.bgsour_idx = 0
        """マップデータのインデックス (0 〜 bgdat_idx_max - 1)"""
        self.bgdest_idx = 32
        """BG データエリアのインデックス (0 〜 63)"""
        self.num_sp = 0
        """スプライトの数"""
        self.use_asm_int = False
        """描画処理でインラインアセンブラを使用するか"""
        self.use_asm_move = False
        """移動処理でインラインアセンブラを使用するか"""

    @classmethod
    def create(
        cls,
        opt_num_sp: int,
        opt_use_asm_int: bool,
        opt_use_asm_move: bool,
        opt_invert_bg: bool,
    ):
        """
        GlobalState インスタンスを作成して初期化する

        @param opt_num_sp スプライトの数
        @param opt_use_asm_int 描画処理でインラインアセンブラを使用する場合は True
        @param opt_use_asm_move 移動処理でインラインアセンブラを使用する場合は True
        @param opt_invert_bg マップデータを反転する場合は True
        @return 初期化済みの GlobalState インスタンス
        """
        instance = cls()

        try:
            instance.spdat = load_binary_file("spdat.bin")  # スプライト座標データ
            instance.bgdat = load_binary_file("bgdat.bin")  # マップデータ
        except OSError as e:
            print(f"Error: {e}")
            exit(1)

        instance.spreg = create_spreg(opt_num_sp)  # 仮想スプライトスクロールレジスタ
        instance.sp_offset0 = (
            len(instance.spdat) // 2 // WORD // 2
        )  # スプライト座標データのオフセット初期値
        instance.sp_offset = instance.sp_offset0  # スプライト座標データのオフセット

        instance.bgdat_idx_max = (
            len(instance.bgdat) // WORD
        )  # マップデータの最大インデックス (ワード単位)
        instance.bgx = 0  # BG の X 表示座標
        instance.bgctr = 0  # BG 更新用カウンタ (0 〜 15)
        instance.bgsour_idx = 0  # マップデータのインデックス (0 〜 bgdat_idx_max - 1)
        instance.bgdest_idx = 32  # BG データエリアのインデックス (0 〜 63)
        instance.num_sp = opt_num_sp  # スプライトの数
        instance.use_asm_int = (
            opt_use_asm_int  # 描画処理でインラインアセンブラを使用するか
        )
        instance.use_asm_move = (
            opt_use_asm_move  # 移動処理でインラインアセンブラを使用するか
        )
        if opt_invert_bg:
            instance.invert_bgdat()

        return instance

    @micropython.viper
    def invert_bgdat(self):
        """
        マップデータを反転する
        """
        p = ptr16(self.bgdat)
        for i in range(int(self.bgdat_idx_max)):
            p[i] ^= 0x0001


@micropython.viper
def vsync_and_render(state):
    """
    垂直帰線期間を待ち、スプライトと BG の表示を行う

    @param state GlobalState インスタンス
    """

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

    # 垂直帰線期間を待つ前にグローバル変数をキャッシュしておく
    _use_asm_int = state.use_asm_int
    _spreg = state.spreg
    _num_sp = state.num_sp
    _bgdat = state.bgdat
    _bgsour_idx = state.bgsour_idx
    _bgdest_idx = state.bgdest_idx
    _bgx = state.bgx
    _bgctr = state.bgctr

    x68k.vsync()  # 垂直帰線期間を待つ

    bgctrlreg = ptr16(BGCTRLREG)
    bgctrlreg[0] = 0x0000  # スプライト / BG の表示をオフにする

    # スプライト

    # 仮想スプライトスクロールレジスタから
    # (実) スプライトスクロールレジスタへブロック転送する
    if _use_asm_int:
        render_asm_sp(_spreg, _num_sp)
    else:
        sp = ptr16(_spreg)
        dp = ptr16(SPSCRLREG)
        for i in range(0, int(_num_sp) * 4, 4):
            dp[i + 0] = sp[i + 0]  # X 座標
            dp[i + 1] = sp[i + 1]  # Y 座標
            dp[i + 2] = sp[i + 2]  # 属性 1
            dp[i + 3] = sp[i + 3]  # 属性 2

    # BG

    # BG の表示 X 座標を更新する
    # (1 ワードの更新なのでインラインアセンブラを使うまでもない？)
    dp = ptr16(BGSCRLREG0)
    dp[0] = int(_bgx)  # BG の表示 X 座標を更新する

    # 16 回スクロールしたら BG を書き直す
    if not _bgctr:
        if _use_asm_int:
            # インラインアセンブラには 5 つ以上の引数を渡せないようだ
            render_asm_bg(_bgdat, _bgsour_idx, _bgdest_idx)
        else:
            sp = ptr16(_bgdat)
            dp = ptr16(BGDATAAREA1)
            i = int(_bgdest_idx)
            j = int(_bgsour_idx)
            for k in range(32):  # 32 キャラクタ分転送する
                dp[i] = sp[j + k]
                i += 64

    bgctrlreg[0] = 0x0203  # スプライト / BG の表示をオンにする


@micropython.viper
def move(state):
    """
    スプライトと BG の移動処理を行う

    @param state GlobalState インスタンス
    """
    # スプライト
    v = int(state.sp_offset) - 1
    if v < 0:
        v = int(state.sp_offset0)  # 座標データのオフセットをリセットする
    state.sp_offset = v

    # BG
    state.bgx = int(state.bgx) + 1  # BG の表示 X 座標を更新する
    v = int(state.bgctr)
    state.bgctr = (v + 1) & 0x0F  # BG 更新用カウンタを更新する
    if v == 0:
        v = int(state.bgsour_idx) + 32  # 縦 32 キャラクタ分進める
        if v >= int(state.bgdat_idx_max):
            v = 0
        state.bgsour_idx = v

        v = int(state.bgdest_idx) + 1
        if v >= 64:
            v = 0
        state.bgdest_idx = v

    update_spbuf(state)  # 仮想スプライトスクロールレジスタを更新する


@micropython.viper
def move_first(state):
    """
    スプライトと BG の移動処理を行う (初回)

    @param state GlobalState インスタンス
    """

    update_spbuf(state)  # 仮想スプライトスクロールレジスタを更新する


@micropython.viper
def update_spbuf(state):
    """
    仮想スプライトスクロールレジスタを更新する

    @param state GlobalState インスタンス
    """
    # スプライト
    v = int(state.sp_offset)
    if state.use_asm_move:
        update_spbuf_asm(state.spdat, state.spreg, v, state.num_sp)
    else:
        spdat_ptr = ptr16(state.spdat)
        spreg_ptr = ptr16(state.spreg)
        i = 0
        for j in range(0, int(state.num_sp) * 4, 4):
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
def mainloop(state):
    """
    メインループ

    @param state GlobalState インスタンス
    """
    with x68k.Super():
        move_first(state)  # 初回
        while True:
            # キーが押されたら終了する
            if (int(x68k.iocs(x68k.i.B_KEYSNS)) & 0xFFFF) and (
                int(x68k.iocs(x68k.i.B_KEYINP)) & 0xFF
            ):
                break
            vsync_and_render(state)  # スプライトと BG の表示を行う
            move(state)  # スプライトと BG の移動処理を行う


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

    state = GlobalState.create(
        opt_num_sp, opt_use_asm_int, opt_use_asm_move, opt_invert_bg
    )

    # デバッグ情報
    if __debug__:
        print("spdat:", hex(uctypes.addressof(state.spdat)))
        print("bgdat:", hex(uctypes.addressof(state.bgdat)))
        print("spreg:", hex(uctypes.addressof(state.spreg)))

    mainloop(state)

    s.disp(False)  # スプライト非表示
    x68k.curon()  # カーソル表示
    exit(0)


main()
