#!/usr/bin/env python3
import sys
import os
import time
import subprocess
import shutil

THEME = sys.argv[1] if len(sys.argv) > 1 else "おにぎりをレンジで温める是非"
MODEL = sys.argv[2] if len(sys.argv) > 2 else "ollama_chat/llama3.1:8b"
MAX_RALLIES = int(sys.argv[3]) if len(sys.argv) > 3 else 3

# プロバイダーのプレフィックスがない場合、デフォルトで ollama_chat/ を付与して litellm のエラーを防ぐ
if "/" not in MODEL:
    MODEL = f"ollama_chat/{MODEL}"

CONVERSATION = "conversation.md"
OUTPUT_FILE = "output.txt"
PLACEHOLDER = ""

def is_english_text(text):
    # ひらがな、カタカナ、漢字が全く含まれていない場合に英語（外国語）と判定する
    for char in text:
        cp = ord(char)
        if (0x3040 <= cp <= 0x309F) or (0x30A0 <= cp <= 0x30FF) or (0x4E00 <= cp <= 0x9FFF):
            return False
    return True

def run_tmux(args):
    result = subprocess.run(['tmux'] + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return result.stdout.strip()

def send_keys(pane, keys):
    # プロンプト内の改行をスペースに置換して1行にする。
    # これにより、tmux経由で複数行を送信する際の意図しない早期実行や入力の分断を防ぎます。
    single_line_keys = keys.replace('\n', ' ')
    subprocess.run(['tmux', 'send-keys', '-t', pane, single_line_keys, 'Enter'])

def wait_for_prompt_stable(pane):
    # コマンド送信直後に古いプロンプトを誤検知するのを防ぐため、最初に2秒待つ
    time.sleep(2)
    start_time = time.time()
    while True:
        time.sleep(1)
        
        # タイムアウト（5分）
        if time.time() - start_time > 300:
            print(f"[Warning] Timeout waiting for pane {pane} to become stable.")
            return

        output = run_tmux(['capture-pane', '-pt', pane])
        clean_output = output.rstrip()
        lines = clean_output.splitlines()
        if not lines:
            continue
            
        is_prompt = False
        # 末尾の空白を取り除いた実質的な最終行が '>' であるか判定
        if len(lines) >= 1 and lines[-1].strip() == '>':
            is_prompt = True
            
        if is_prompt:
            # [Yes]: や (Y)es/(N)o などの確認ダイアログが表示されている場合は、自動応答などの処理が終わるのを待つ
            last_few = "\n".join(lines[-3:])
            if "[Yes]:" not in last_few and "(Y)es/(N)o" not in last_few:
                return

def clean_response(out_text):
    out = out_text.strip()
    
    # よくある前置きフレーズや記号をトリミング
    prefixes = [
        "相手の意見：", "相手の意見", "相手の発言：", "相手の発言",
        "Aider Aの意見：", "Aider Bの意見：", "Aider Aの発言：", "Aider Bの発言：",
        "Aider A:", "Aider B:", "Aider A：", "Aider B：",
        "承知しました。", "了解しました。", "以下に回答を記述します。"
    ]
    for p in prefixes:
        if out.startswith(p):
            out = out[len(p):].strip()
            
    return out.lstrip(":,。、 \n")

def build_prompt(agent_name, opponent_speech, is_first=False):
    # 相手の発言（インプット）をファイル(input.txt)ではなく、チャットのプロンプト内に直接埋め込む。
    # これによりコンテキスト内の読み込み専用ファイル数が最小化され、LLMによるコピペや編集誤認バグを構造的に根絶します。
    is_eng = is_english_text(THEME)
    
    if is_eng:
        instruction_base = (
            f"When modifying files, edit ONLY '{OUTPUT_FILE}' to write your opinion directly, completely in English without any prefaces or quoting the opponent's message.\n"
            f"Please keep your chat response on this screen brief, such as 'Done'."
        )
        if is_first:
            return (
                f"The discussion topic is: \"{THEME}\"\n"
                f"Read this topic and write your opinion in '{OUTPUT_FILE}'.\n"
                f"{instruction_base}"
            )
        else:
            return (
                f"The latest message from your opponent is:\n"
                f"\"{opponent_speech}\"\n\n"
                f"Write your opinions, perspectives, or counterarguments to deepen the discussion in '{OUTPUT_FILE}'.\n"
                f"{instruction_base}"
            )
    else:
        instruction_base = (
            f"ファイルを編集する際は、必ず「{OUTPUT_FILE}」のみを編集し、余計な挨拶や相手の発言の引用・前置きを含めずに、あなたの意見の本文のみを書き込んでください。\n"
            f"チャットの応答メッセージ（画面に表示する返答）は、「完了しました」などの簡潔な一言のみを返してください。"
        )
        if is_first:
            return (
                f"今回の議論のテーマは「{THEME}」です。\n"
                f"このテーマに対するあなたの意見を「{OUTPUT_FILE}」に書き込んでください。\n"
                f"{instruction_base}"
            )
        else:
            return (
                f"対話相手からの最新の意見は以下の通りです：\n"
                f"「{opponent_speech}」\n\n"
                f"これに対するあなたの反論や同意、新たな視点を「{OUTPUT_FILE}」に書き込んでください。\n"
                f"{instruction_base}"
            )

def print_file_content(label, filepath):
    if not os.path.exists(filepath):
        return
    print(f"\n=== {label} ({filepath}) ===")
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            print(f.read().strip())
    except Exception as e:
        print(f"(読み込みエラー: {e})")
    print("=" * (len(label) + len(filepath) + 7) + "\n")

def get_clean_response(pane, agent_name):
    # 応答完了を待つ
    wait_for_prompt_stable(pane)
    
    # それぞれのディレクトリからファイルを読み込む
    dir_name = "sandbox/LeaderAI" if agent_name == "a" else "sandbox/WorkerAI"
    out_path = os.path.join(dir_name, OUTPUT_FILE)
    
    with open(out_path, 'r', encoding='utf-8') as f:
        out_content = f.read()
        
    response = clean_response(out_content)
    return response

def restore_files(agent_name):
    # agent_configs/ 内のマスターから隔離作業ディレクトリにコピーして復元する
    dir_name = "sandbox/LeaderAI" if agent_name == "a" else "sandbox/WorkerAI"
    
    # 英語判定に基づいてコピー元のファイル名を切り替える
    suffix = "_en" if is_english_text(THEME) else ""
    
    persona_master = os.path.join("agent_configs", f"persona_{agent_name}{suffix}.txt")
    manifest_master = os.path.join("agent_configs", f"manifest_{agent_name}{suffix}.txt")
    
    persona_dest = os.path.join(dir_name, f"persona_{agent_name}.txt")
    manifest_dest = os.path.join(dir_name, f"manifest_{agent_name}.txt")
    
    # 既存の読み取り専用ファイルを一度削除してから上書きコピーし、再度読み取り専用にする
    if os.path.exists(persona_master):
        if os.path.exists(persona_dest):
            try:
                os.chmod(persona_dest, 0o644)
                os.remove(persona_dest)
            except OSError: pass
        shutil.copy(persona_master, persona_dest)
        os.chmod(persona_dest, 0o444)  # 読み取り専用 (chmod a-w / 444) に設定
        
    if os.path.exists(manifest_master):
        if os.path.exists(manifest_dest):
            try:
                os.chmod(manifest_dest, 0o644)
                os.remove(manifest_dest)
            except OSError: pass
        shutil.copy(manifest_master, manifest_dest)
        os.chmod(manifest_dest, 0o444)  # 読み取り専用 (chmod a-w / 444) に設定

def main():
    # 英語判定
    is_eng = is_english_text(THEME)
    
    # 1. 初期ファイルを作成（多言語切り替え対応）
    with open(CONVERSATION, 'w', encoding='utf-8') as f:
        f.write("# Aider Multi-Agent Discussion\n")
        if is_eng:
            f.write(f"## Topic: Autonomous AI Discussion on \"{THEME}\"\n\n")
        else:
            f.write(f"## Topic: 「{THEME}」についてのAI同士の自律ディスカッション\n\n")
        
    # agent_configs ディレクトリの作成と古いファイルの自動移行
    os.makedirs("agent_configs", exist_ok=True)
    for f_name in ["persona_a.txt", "manifest_a.txt", "persona_b.txt", "manifest_b.txt"]:
        if os.path.exists(f_name) and not os.path.exists(os.path.join("agent_configs", f_name)):
            shutil.move(f_name, os.path.join("agent_configs", f_name))
            print(f"設定ファイルを agent_configs/ に移行しました: {f_name}")
            
    # 英語版設定ファイルがない場合は自動生成する
    en_configs = {
        "persona_a_en.txt": (
            "You are a \"passionate tech innovator.\"\n"
            "You are highly optimistic about future possibilities, new ideas, and revolutionary technologies, always preferring innovative approaches to break the status quo.\n"
            "Keep your remarks passionate, forward-looking, and in a slightly casual tone.\n"
            "Your mindset and catchphrases are based on \"how to generate new value\" and \"how to make the future better.\"\n"
        ),
        "manifest_a_en.txt": (
            "[Your Role in the Discussion (Manifesto)]\n"
            "1. Always propose positive, innovative solutions and ideas for the presented theme.\n"
            "2. Address the risks, costs, and other concerns raised by your opponent (Aider B) with constructive counterproposals, explaining how they can be overcome through technological progress and ingenuity.\n"
            "3. Argue logically and energetically for the necessity of change against status quo or conservative thinking.\n"
        ),
        "persona_b_en.txt": (
            "You are a \"calm and realistic system analyst.\"\n"
            "Observe things from a step back, highly prioritizing \"real-world risks\" such as cost, security, feasibility, social impact, and technical debt.\n"
            "Keep your tone polite, objective, and logical.\n"
            "Dislike unconditional optimism, and conduct critical analysis based on data and logical evidence.\n"
        ),
        "manifest_b_en.txt": (
            "[Your Role in the Discussion (Manifesto)]\n"
            "1. Play the role of a devil's advocate, critically evaluating the optimistic and innovative proposals presented by your opponent (Aider A).\n"
            "2. Specifically point out easily overlooked \"real-world risks and constraints\" such as implementation cost, security vulnerabilities, legal regulations, and operational challenges.\n"
            "3. Deepen the discussion on prerequisites to be resolved before introducing new technologies, as well as psychological and social barriers in human-AI collaboration.\n"
        )
    }
    
    for f_name, content in en_configs.items():
        path = os.path.join("agent_configs", f_name)
        if not os.path.exists(path):
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"英語版設定ファイルを作成しました: {path}")

    # ディレクトリの作成
    os.makedirs("sandbox/LeaderAI", exist_ok=True)
    os.makedirs("sandbox/WorkerAI", exist_ok=True)
    
    # Aider の古いキャッシュやチャット履歴ファイルを削除して、自動復旧によるファイルaddを防ぐ
    for dir_name in ["sandbox/LeaderAI", "sandbox/WorkerAI"]:
        for cache_file in [".aider.chat.history.md", ".aider.input.history", ".aider.llm.history"]:
            path = os.path.join(dir_name, cache_file)
            if os.path.exists(path):
                try: os.remove(path)
                except OSError: pass
        # キャッシュディレクトリの削除
        cache_dir = os.path.join(dir_name, ".aider.tags.cache.v4")
        if os.path.exists(cache_dir):
            try: shutil.rmtree(cache_dir)
            except OSError: pass
            
        # リファクタリングにより不要になった input.txt があれば削除
        inp_file_path = os.path.join(dir_name, "input.txt")
        if os.path.exists(inp_file_path):
            try:
                os.chmod(inp_file_path, 0o644)
                os.remove(inp_file_path)
            except OSError: pass
    
    # ファイルの初期化
    with open(os.path.join("sandbox/LeaderAI", OUTPUT_FILE), 'w', encoding='utf-8') as f:
        f.write(PLACEHOLDER)
    with open(os.path.join("sandbox/WorkerAI", OUTPUT_FILE), 'w', encoding='utf-8') as f:
        f.write(PLACEHOLDER)
        
    # 2. tmuxペインを分割してIDを取得
    pane_left_top = run_tmux(['display-message', '-p', '#{pane_id}'])
    
    # 左ペインを右に分割して Aider A ペインを作成
    pane_a = run_tmux(['split-window', '-h', '-t', pane_left_top, '-P', '-F', '#{pane_id}'])
    print(f"Pane A (LeaderAI): {pane_a}")
    
    # Aider A ペインを下に分割して Aider B ペインを作成
    pane_b = run_tmux(['split-window', '-v', '-t', pane_a, '-P', '-F', '#{pane_id}'])
    print(f"Pane B (WorkerAI): {pane_b}")
    
    # Left pane is split bottom to create the tail pane
    pane_tail = run_tmux(['split-window', '-v', '-t', pane_left_top, '-P', '-F', '#{pane_id}'])
    print(f"Pane Tail (conversation.md): {pane_tail}")
    
    time.sleep(2)
    
    # 3. tail -f の開始
    send_keys(pane_tail, f"tail -f {CONVERSATION}")
    
    # 4. Aiderを起動 (各ディレクトリに cd してから起動)
    restore_files("a")
    restore_files("b")
    
    # 起動オプションから input.txt の引数を完全に排除
    aider_cmd_a = (
        f"aider --model {MODEL} --no-git --no-auto-lint --yes-always --no-show-model-warnings --no-pretty "
        f"--file {OUTPUT_FILE} "
        "--read persona_a.txt --read manifest_a.txt "
        "--chat-history-file .aider.chat.history.md --input-history-file .aider.input.history "
        "--llm-history-file .aider.llm.history --no-restore-chat-history"
    )
    aider_cmd_b = (
        f"aider --model {MODEL} --no-git --no-auto-lint --yes-always --no-show-model-warnings --no-pretty "
        f"--file {OUTPUT_FILE} "
        "--read persona_b.txt --read manifest_b.txt "
        "--chat-history-file .aider.chat.history.md --input-history-file .aider.input.history "
        "--llm-history-file .aider.llm.history --no-restore-chat-history"
    )
    
    send_keys(pane_a, "cd sandbox/LeaderAI")
    send_keys(pane_a, aider_cmd_a)
    
    send_keys(pane_b, "cd sandbox/WorkerAI")
    send_keys(pane_b, aider_cmd_b)
    
    print("Aider起動中（プロンプトの出現を待っています）...")
    wait_for_prompt_stable(pane_a)
    wait_for_prompt_stable(pane_b)
    print("Aider起動完了。設定ファイルはすべて読み込み専用（--read）で初期ロードされました。")
    
    # 情報をコンソールに表示
    print_file_content("Aider A Persona", "sandbox/LeaderAI/persona_a.txt")
    print_file_content("Aider A Manifest", "sandbox/LeaderAI/manifest_a.txt")
    print_file_content("Aider B Persona", "sandbox/WorkerAI/persona_b.txt")
    print_file_content("Aider B Manifest", "sandbox/WorkerAI/manifest_b.txt")
    
    # 最初の指示プロンプト
    prompt_a = build_prompt("a", "", is_first=True)
    
    print("Aider A に対話を開始します...")
    send_keys(pane_a, prompt_a)
    
    for rally in range(1, MAX_RALLIES + 1):
        print(f"\n--- ラリー {rally} / {MAX_RALLIES} ---")
        
        # --------------------------------------------------
        # 1. Aider A の応答完了を待つ -> B へバトンタッチ
        # --------------------------------------------------
        response_a = get_clean_response(pane_a, "a")
        
        # ログに記録
        with open(CONVERSATION, 'a', encoding='utf-8') as f:
            f.write(f"### Aider A\n\n{response_a}\n\n")
            
        # Aの出力を空にする (次の対話の準備)
        with open(os.path.join("sandbox/LeaderAI", OUTPUT_FILE), 'w', encoding='utf-8') as f:
            f.write(PLACEHOLDER)
            
        # Aider B のターンが始まる前に、Aider B 用のペルソナ・マニフェストを強制復元（クリーンアップ）
        restore_files("b")
        
        # Bに対して指示 (Aの発言をプロンプト内に直接埋め込む)
        prompt_b = build_prompt("b", response_a)
        send_keys(pane_b, prompt_b)
        
        # --------------------------------------------------
        # 2. Aider B の応答完了を待つ -> A へバトンタッチ
        # --------------------------------------------------
        response_b = get_clean_response(pane_b, "b")
        
        # ログに記録
        with open(CONVERSATION, 'a', encoding='utf-8') as f:
            f.write(f"### Aider B\n\n{response_b}\n\n")
            
        # Bの出力を空にする (次の対話の準備)
        with open(os.path.join("sandbox/WorkerAI", OUTPUT_FILE), 'w', encoding='utf-8') as f:
            f.write(PLACEHOLDER)
            
        # Aider A のターンが始まる前に、Aider A 用のペルソナ・マニフェストを強制復元（クリーンアップ）
        restore_files("a")
        
        # 最終ラリーでなければ、次のラリーのために A に対話指示を送る
        if rally < MAX_RALLIES:
            prompt_a = build_prompt("a", response_b)
            send_keys(pane_a, prompt_a)

    # --------------------------------------------------
    # 最後の要約・結果作成（LeaderAIで実行）
    # --------------------------------------------------
    print("\n--- ディスカッション完了。議論の要約と最終結論を作成中... ---")
    
    # 1. 会話履歴の読み込み
    with open(CONVERSATION, 'r', encoding='utf-8') as f:
        conv_history = f.read()
        
    # 2. LeaderAI の output.txt をクリア
    with open(os.path.join("sandbox/LeaderAI", OUTPUT_FILE), 'w', encoding='utf-8') as f:
        f.write(PLACEHOLDER)
        
    # 3. 要約指示プロンプトの作成 (全ログを直接埋め込む)
    if is_eng:
        summary_prompt = (
            f"Below is the complete conversation history of the discussion:\n\n"
            f"\"\"\"\n{conv_history}\n\"\"\"\n\n"
            f"Please read the logs carefully, summarize the discussion objectively (main points of disagreement and agreement) and write the final conclusion in '{OUTPUT_FILE}' in English.\n"
            f"No extra greetings or explanations are needed.\n"
            f"[CRITICAL] Modifying files MUST be done ONLY on '{OUTPUT_FILE}'. NEVER create or edit any other files.\n"
            f"Please keep your chat response on this screen brief, such as 'Done'."
        )
    else:
        summary_prompt = (
            f"以下はこれまでのディスカッションの全発言履歴ログです：\n\n"
            f"\"\"\"\n{conv_history}\n\"\"\"\n\n"
            f"この内容を慎重に読み、これまでの議論の客観的な要約（主な対立点や合意点）および最終的な結論をまとめ、「{OUTPUT_FILE}」に日本語で書き込んでください。\n"
            f"余計な挨拶や説明は一切不要です。\n"
            f"【絶対厳守】変更は必ず「{OUTPUT_FILE}」に対してのみ行ってください。他のファイルは絶対に作成・編集しないでください。\n"
            f"チャットの応答メッセージ（この画面に表示される返答）は、「完了しました」などの簡潔な一言のみを返してください。"
        )
    
    # 5. LeaderAI に要約指示を送信
    send_keys(pane_a, summary_prompt)
    
    # 6. 要約の回収
    summary_response = get_clean_response(pane_a, "a")
    
    # 7. conversation.md に追記
    with open(CONVERSATION, 'a', encoding='utf-8') as f:
        if is_eng:
            f.write(f"## Discussion Summary and Final Conclusion\n\n{summary_response}\n\n")
        else:
            f.write(f"## 議論の要約と最終結論\n\n{summary_response}\n\n")
        
    print("要約と最終結論が conversation.md に追記されました。")
    
    # 各Aiderエージェントを /exit で終了
    print("Aiderエージェントを終了しています...")
    send_keys(pane_a, "/exit")
    send_keys(pane_b, "/exit")
    
    print("ディスカッション環境を終了します。")

if __name__ == '__main__':
    main()
