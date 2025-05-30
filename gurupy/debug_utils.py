import micropython

if __debug__:

    @micropython.viper
    def get_buffer_address(buf) -> int:
        """
        バッファの先頭アドレスを取得する

        @param buf アドレスを取得したいバッファ
        @return バッファの先頭アドレス
        """
        p = ptr8(buf)
        # アドレスを整数として取得
        return int(p)

    def print_buffer_info(name, buf):
        """
        バッファの情報をデバッグ出力する

        @param name バッファの名前
        @param buf アドレスを表示したいバッファ
        """
        print(f"{name}:", hex(get_buffer_address(buf)))
else:

    def get_buffer_address(buf) -> int:
        """
        デバッグモードでない場合のダミー実装

        @param buf アドレスを取得したいバッファ
        @return 常に 0
        """
        return 0

    def print_buffer_info(name, buf):
        """
        デバッグモードでない場合のダミー実装

        @param name バッファの名前
        @param buf アドレスを表示したいバッファ
        """
        pass  # 何もしない
