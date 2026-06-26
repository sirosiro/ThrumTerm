#!/usr/bin/env python3
import sys
import os
import time
import subprocess
import shutil

THEME = sys.argv[1] if len(sys.argv) > 1 else "おにぎりをレンジで温める是非"

CONVERSATION = "conversation.md"
INPUT_FILE = "input.txt"
OUTPUT_FILE = "output.txt"
PLACEHOLDER = ""

def run_tmux(args):
    result = subprocess.run(['tmux'] + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return result.stdout.strip()

def send_keys(pane, keys):
    subprocess.run(['tmux', 'send-keys', '-t', pane, keys, 'Enter'])

def wait_for_prompt_simple(pane):
    # 送信直後の誤認識を防ぐため、呼び出し側で先に sleep 3 しておくことを前提とする
    while True:
        time.sleep(2)
        output = run_tmux(['capture-pane', '-pt', pane])
        lines = output.splitlines()
        
        is_prompt = False
        if len(lines) >= 1 and lines[-1].strip() == '>':
            is_prompt = True
        elif len(lines) >= 2 and lines[-2].strip() == '>':
            is_prompt = True
            
        if is_prompt:
            return

def clean_response(inp_text, out_text):
    out = out_text.strip()
    inp = inp_text.strip()
    
    # 相手の元の発言（inp）が out の中に部分的に含まれている場合、そこまでをカット
    if inp:
        # 入力テキストの最後の30文字（短ければ全体）を検索キーとする
        search_len = min(len(inp), 30)
        inp_suffix = inp[-search_len:]
        
        # 出力の先頭から150文字以内で検索キーが見つかるか？
        idx = out.find(inp_suffix)
        if 0 <= idx < 150:
            # 見つかった位置 + 検索キーの長さより後ろを新しい出力とする
            out = out[idx + len(inp_suffix):].strip()
            
    # よくある前置きフレーズをトリミング
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

def build_prompt(agent_name, is_first=False):
    if is_first:
        return f"{INPUT_FILE} の内容（議論のテーマ）を読み、それに対するあなたの意見を {OUTPUT_FILE} に書き込んでください。余計な挨拶や説明は一切不要です。"
    else:
        if agent_name == "a":
            return f"{INPUT_FILE} が更新されました。これに対するあなたの意見や議論を深める視点を {OUTPUT_FILE} に書き込んでください。余計な挨拶や説明、相手の発言のコピーや同じ文章の繰り返しは絶対に避けてください。"
        else:
            return f"{INPUT_FILE} が更新されました。これに対するあなたの反論や同意、新たな視点を {OUTPUT_FILE} に書き込んでください。余計な挨拶や説明、相手の発言のコピーや同じ文章の繰り返しは絶対に避けてください。"

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
    wait_for_prompt_simple(pane)
    
    # それぞれのディレクトリからファイルを読み込む
    dir_name = f"ai0{1 if agent_name == 'a' else 2}"
    inp_path = os.path.join(dir_name, INPUT_FILE)
    out_path = os.path.join(dir_name, OUTPUT_FILE)
    
    with open(inp_path, 'r', encoding='utf-8') as f:
        inp_content = f.read()
    with open(out_path, 'r', encoding='utf-8') as f:
        out_content = f.read()
        
    response = clean_response(inp_content, out_content)
    return response

def restore_files(agent_name):
    # agent_configs/ 内のマスターから隔離作業ディレクトリ（sandbox/LeaderAI/sandbox/WorkerAI）にコピーして復元する
    dir_name = f"ai0{1 if agent_name == 'a' else 2}"
    
    persona_master = os.path.join("agent_configs", f"persona_{agent_name}.txt")
    manifest_master = os.path.join("agent_configs", f"manifest_{agent_name}.txt")
    
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
    # 1. 初期ファイルを作成
    with open(CONVERSATION, 'w', encoding='utf-8') as f:
        f.write("# Aider Multi-Agent Discussion\n")
        f.write(f"## Topic: 「{THEME}」についてのAI同士の自律ディスカッション\n\n")
        
    # agent_configs ディレクトリの作成と古いファイルの自動移行
    os.makedirs("agent_configs", exist_ok=True)
    for f_name in ["persona_a.txt", "manifest_a.txt", "persona_b.txt", "manifest_b.txt"]:
        if os.path.exists(f_name) and not os.path.exists(os.path.join("agent_configs", f_name)):
            shutil.move(f_name, os.path.join("agent_configs", f_name))
            print(f"設定ファイルを agent_configs/ に移行しました: {f_name}")
            
    # ディレクトリの作成
    os.makedirs("sandbox/LeaderAI", exist_ok=True)
    os.makedirs("sandbox/WorkerAI", exist_ok=True)
    
    # Aider の古いキャッシュやチャット履歴ファイルを削除して、自動復旧によるファイルaddを防ぐ
    for dir_name in ["sandbox/LeaderAI", "sandbox/WorkerAI"]:
        for cache_file in [".aider.chat.history.md", ".aider.input.history"]:
            path = os.path.join(dir_name, cache_file)
            if os.path.exists(path):
                try: os.remove(path)
                except OSError: pass
        # キャッシュディレクトリの削除
        cache_dir = os.path.join(dir_name, ".aider.tags.cache.v4")
        if os.path.exists(cache_dir):
            try: shutil.rmtree(cache_dir)
            except OSError: pass
    
    # ファイルの初期化
    with open(os.path.join("sandbox/LeaderAI", INPUT_FILE), 'w', encoding='utf-8') as f:
        f.write(THEME)
    with open(os.path.join("sandbox/LeaderAI", OUTPUT_FILE), 'w', encoding='utf-8') as f:
        f.write(PLACEHOLDER)
        
    with open(os.path.join("sandbox/WorkerAI", INPUT_FILE), 'w', encoding='utf-8') as f:
        f.write("")
    with open(os.path.join("sandbox/WorkerAI", OUTPUT_FILE), 'w', encoding='utf-8') as f:
        f.write(PLACEHOLDER)
        
    # 2. tmuxペインを分割してIDを取得
    pane_a = run_tmux(['split-window', '-h', '-P', '-F', '#{pane_id}'])
    print(f"Pane A: {pane_a}")
    pane_b = run_tmux(['split-window', '-v', '-P', '-F', '#{pane_id}'])
    print(f"Pane B: {pane_b}")
    
    time.sleep(2)
    
    # 3. Aiderを起動 (各ディレクトリに cd してから起動)
    restore_files("a")
    restore_files("b")
    
    # 起動オプションで直接 read-only/edit ファイルを指定し、履歴ファイルも各ディレクトリ内に隔離
    aider_cmd_a = (
        "aider --model ollama_chat/llama3.2:3b --no-git --no-auto-lint --yes-always "
        f"--read {INPUT_FILE} --file {OUTPUT_FILE} "
        "--read persona_a.txt --read manifest_a.txt "
        "--chat-history-file .aider.chat.history.md --input-history-file .aider.input.history --no-restore-chat-history"
    )
    aider_cmd_b = (
        "aider --model ollama_chat/llama3.2:3b --no-git --no-auto-lint --yes-always "
        f"--read {INPUT_FILE} --file {OUTPUT_FILE} "
        "--read persona_b.txt --read manifest_b.txt "
        "--chat-history-file .aider.chat.history.md --input-history-file .aider.input.history --no-restore-chat-history"
    )
    
    send_keys(pane_a, "cd sandbox/LeaderAI")
    send_keys(pane_a, aider_cmd_a)
    
    send_keys(pane_b, "cd sandbox/WorkerAI")
    send_keys(pane_b, aider_cmd_b)
    
    print("Aider起動中（プロンプトの出現を待っています）...")
    time.sleep(2)
    # Aiderが起動して最初のプロンプト '>' が表示されるのを確実に待つ
    wait_for_prompt_simple(pane_a)
    wait_for_prompt_simple(pane_b)
    print("Aider起動完了。設定ファイルはすべて読み込み専用（--read）で初期ロードされました。")
    
    # 情報をコンソールに表示
    print_file_content("Aider A Persona", "sandbox/LeaderAI/persona_a.txt")
    print_file_content("Aider A Manifest", "sandbox/LeaderAI/manifest_a.txt")
    print_file_content("Aider B Persona", "sandbox/WorkerAI/persona_b.txt")
    print_file_content("Aider B Manifest", "sandbox/WorkerAI/manifest_b.txt")
    
    # 最初の指示プロンプト
    prompt_a = build_prompt("a", is_first=True)
    
    print("Aider A に対話を開始します...")
    send_keys(pane_a, prompt_a)
    
    while True:
        # 送信直後の誤認識を防ぐために少し待つ
        time.sleep(3)
        
        # --------------------------------------------------
        # 1. Aider A の応答完了を待つ -> B へバトンタッチ
        # --------------------------------------------------
        response = get_clean_response(pane_a, "a")
        
        # ログに記録
        with open(CONVERSATION, 'a', encoding='utf-8') as f:
            f.write(f"### Aider A\n\n{response}\n\n")
            
        # 次のターンの準備 (Aの出力をBの入力に書き込み、Aの出力を空にする)
        with open(os.path.join("sandbox/WorkerAI", INPUT_FILE), 'w', encoding='utf-8') as f:
            f.write(response)
        with open(os.path.join("sandbox/LeaderAI", OUTPUT_FILE), 'w', encoding='utf-8') as f:
            f.write(PLACEHOLDER)
            
        # Aider B のターンが始まる前に、Aider B 用のペルソナ・マニフェストを強制復元（クリーンアップ）
        restore_files("b")
        
        time.sleep(2)
        
        # Bに対して指示
        prompt_b = build_prompt("b")
        send_keys(pane_b, prompt_b)
        
        # 送信直後の誤認識を防ぐために少し待つ
        time.sleep(3)
        
        # --------------------------------------------------
        # 2. Aider B の応答完了を待つ -> A へバトンタッチ
        # --------------------------------------------------
        response = get_clean_response(pane_b, "b")
        
        # ログに記録
        with open(CONVERSATION, 'a', encoding='utf-8') as f:
            f.write(f"### Aider B\n\n{response}\n\n")
            
        # 次のターンの準備 (Bの出力をAの入力に書き込み、Bの出力を空にする)
        with open(os.path.join("sandbox/LeaderAI", INPUT_FILE), 'w', encoding='utf-8') as f:
            f.write(response)
        with open(os.path.join("sandbox/WorkerAI", OUTPUT_FILE), 'w', encoding='utf-8') as f:
            f.write(PLACEHOLDER)
            
        # Aider A のターンが始まる前に、Aider A 用のペルソナ・マニフェストを強制復元（クリーンアップ）
        restore_files("a")
        
        time.sleep(2)
        
        # Aに対して指示
        prompt_a = build_prompt("a")
        send_keys(pane_a, prompt_a)

if __name__ == '__main__':
    main()
