#!/usr/bin/env encoding=utf-8 python3
import sys
import os
import time
import subprocess
import shutil
import json

# ==============================================================================
# Global Constants & Input Parsing
# ==============================================================================
THEME = sys.argv[1] if len(sys.argv) > 1 else "おにぎりをレンジで温める是非"
MODEL = sys.argv[2] if len(sys.argv) > 2 else "ollama_chat/llama3.1:8b"
MAX_RALLIES = int(sys.argv[3]) if len(sys.argv) > 3 else 3

# Add ollama provider prefix fallback if missing
if "/" not in MODEL:
    MODEL = f"ollama_chat/{MODEL}"

CONVERSATION = "discussion_log.md"


# ==============================================================================
# Helper classes & Utilities
# ==============================================================================
class LanguageDetector:
    """Detects if the given text should be treated as English or Japanese."""
    @staticmethod
    def is_english(text: str) -> bool:
        # Returns True if the text contains no Hiragana, Katakana, or Kanji characters.
        for char in text:
            cp = ord(char)
            if (0x3040 <= cp <= 0x309F) or (0x30A0 <= cp <= 0x30FF) or (0x4E00 <= cp <= 0x9FFF):
                return False
        return True


class TmuxSession:
    """Manages low-level interactions with tmux panes and CLI interfaces."""
    @staticmethod
    def run_command(args: list) -> str:
        result = subprocess.run(['tmux'] + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return result.stdout.strip()

    @classmethod
    def send_keys(cls, pane_id: str, keys: str):
        # Replace line breaks with spaces to prevent accidental partial executions
        single_line_keys = keys.replace('\n', ' ')
        subprocess.run(['tmux', 'send-keys', '-t', pane_id, single_line_keys, 'Enter'])

    @classmethod
    def wait_for_prompt_stable(cls, pane_id: str, timeout_seconds: int = 300):
        # Prevent picking up the old prompt immediately
        time.sleep(2)
        start_time = time.time()
        while True:
            time.sleep(1)
            
            if time.time() - start_time > timeout_seconds:
                print(f"[Warning] Timeout waiting for pane {pane_id} to become stable.")
                return

            output = cls.run_command(['capture-pane', '-pt', pane_id])
            clean_output = output.rstrip()
            lines = clean_output.splitlines()
            if not lines:
                continue
                
            is_prompt = False
            # Check if the last line ends with prompt character '>' or shell markers like '%' or '$'
            # after Aider exits
            if len(lines) >= 1:
                last_line = lines[-1].strip()
                if last_line == '>' or last_line.endswith('%') or last_line.endswith('$'):
                    is_prompt = True
                
            if is_prompt:
                # Wait longer if confirmation dialogs (Yes/No) are blocking the prompt
                last_few = "\n".join(lines[-3:])
                if "[Yes]:" not in last_few and "(Y)es/(N)o" not in last_few:
                    return


class AgentConfig:
    """Manages AGENTS.md configuration for an agent by combining persona and manifesto."""
    def __init__(self, agent_name: str, theme: str):
        self.agent_name = agent_name
        self.theme = theme
        self.is_eng = LanguageDetector.is_english(theme)
        self.dir_name = "sandbox/LeaderAI" if agent_name == "a" else "sandbox/WorkerAI"
        
    def restore(self):
        # Pick English settings if the theme language is English
        suffix = "_en" if self.is_eng else ""
        
        persona_master = os.path.join("agent_configs", f"persona_{self.agent_name}{suffix}.txt")
        manifest_master = os.path.join("agent_configs", f"manifest_{self.agent_name}{suffix}.txt")
        
        agents_md_dest = os.path.join(self.dir_name, "AGENTS.md")
        
        # Unlock and delete existing AGENTS.md if it exists
        if os.path.exists(agents_md_dest):
            try:
                os.chmod(agents_md_dest, 0o644)
                os.remove(agents_md_dest)
            except OSError: pass
            
        # Read and merge persona and manifesto into AGENTS.md
        combined_content = ""
        
        # Embed the discussion topic as the main header of AGENTS.md so the LLM always remembers it
        if self.is_eng:
            combined_content += f"# Discussion Theme: \"{self.theme}\"\n\n"
        else:
            combined_content += f"# ディスカッションテーマ: 「{self.theme}」\n\n"
            
        if os.path.exists(persona_master):
            with open(persona_master, 'r', encoding='utf-8') as f:
                combined_content += f.read()
                
        if os.path.exists(manifest_master):
            combined_content += "\n\n"
            with open(manifest_master, 'r', encoding='utf-8') as f:
                combined_content += f.read()
                
        # Append the critical instructions specified by the user (locale-aware)
        # Note: Do not prohibit markdown code blocks (```) in general because Aider requires them
        # to format its file edit commands (e.g. whole/diff blocks). Prohibit them ONLY within the written file body.
        # Add strict rules prohibiting copying/repeating opponent's claims or duplicating previous statements.
        # Enforce paraphrase and grammatical variation to break loop repetitions.
        combined_content += "\n\n"
        if self.is_eng:
            combined_content += (
                "[CRITICAL CONVENTIONS / RULES]\n"
                "1. Your mission is to \"completely overwrite (full replace)\" the contents of 'output.txt' with your own opinion. Produce the correct Aider editing block (e.g. markdown code blocks) to update 'output.txt'.\n"
                "2. Within the body text written to 'output.txt', do NOT include any greetings, prefaces, program code explanations, or markdown formatting (```). Write ONLY the plain body text of your opinion.\n"
                "3. [STRICT RULE] Never copy, repeat, or quote the opponent's message in your written output. Stating or repeating identical claims/expressions from previous turns is strictly forbidden. Paraphrase your points completely using different vocabulary and sentence structures.\n"
                "4. Deeply ponder the opponent's message and your assigned role before developing your next opinion or counterargument."
            )
        else:
            combined_content += (
                "【絶対厳守のコーディング・出力ルール】\n"
                "1. あなたの任務は、output.txt の内容をあなたの意見で「完全に上書き（フルリプレイス）」することです。Aiderのファイル更新ルールに従い、output.txt を更新するための編集ブロックを出力してください。\n"
                "2. output.txt のファイル内に書き込む本文には、余計な挨拶、前置き、プログラムコードの解説、バックティック（```）によるマークダウン装飾を含めず、あなたの主張の本文のみを直接記述してください。\n"
                "3. 【厳重ルール・繰り返し禁止】対話相手の発言をコピー（引用・記述）しないでください。また、前回の自分の発言と「全く同じ文章」「同じ論理展開」「同一の語尾表現」を繰り返すことを厳重に禁止します。主張を再展開する際は、異なる単語や表現に完全にパラフレーズ（言い換え）し、必ず新しい根拠や具体例を追加して議論を前進させてください。\n"
                "4. 対話相手の意見と与えられた役割を深く熟考した上で、次の意見や反論を展開してください。"
            )
                
        # Write merged file to destination
        with open(agents_md_dest, 'w', encoding='utf-8') as f:
            f.write(combined_content)
            
        # Lock destination as read-only (chmod 444) to prevent LLM modification
        os.chmod(agents_md_dest, 0o444)


class InputOutputController:
    """Handles read/write and state-locking for input/output files of agents."""
    INPUT_FILE = "input.txt"
    OUTPUT_FILE = "output.txt"
    
    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.dir_name = "sandbox/LeaderAI" if agent_name == "a" else "sandbox/WorkerAI"
        self.out_path = os.path.join(self.dir_name, self.OUTPUT_FILE)
        self.inp_path = os.path.join(self.dir_name, self.INPUT_FILE)
        
    def write_raw_input(self, content: str):
        # Writes raw content directly to input.txt and locks it.
        # This prevents metadata pollution and lets LLMs focus on raw text logs.
        if os.path.exists(self.inp_path):
            try: os.chmod(self.inp_path, 0o644)
            except OSError: pass
            
        with open(self.inp_path, 'w', encoding='utf-8') as f:
            f.write(content)
        os.chmod(self.inp_path, 0o444)  # Lock input.txt as read-only
        
    def read_output(self) -> str:
        if not os.path.exists(self.out_path):
            return ""
        with open(self.out_path, 'r', encoding='utf-8') as f:
            out_content = f.read()
        return self._clean(out_content)
        
    def create_empty_output(self):
        # Creates an empty output.txt file to ensure Aider doesn't report file not found
        # or drop output.txt from the chat session. Size 0 file acts as a clean slate.
        if os.path.exists(self.out_path):
            try:
                os.chmod(self.out_path, 0o644)
                os.remove(self.out_path)
            except OSError: pass
            
        with open(self.out_path, 'w', encoding='utf-8') as f:
            f.write("")
            
    def move_to_opponent_input(self, opponent_io):
        # Moves this agent's output.txt to the opponent's input.txt directly.
        # This naturally deletes output.txt, prevents patch-merge errors,
        # and avoids adding metadata headers to prevent prompt contamination.
        src = self.out_path
        dst = opponent_io.inp_path
        
        # Unlock destination if it exists
        if os.path.exists(dst):
            try: os.chmod(dst, 0o644)
            except OSError: pass
            
        if os.path.exists(src):
            try: os.chmod(src, 0o644)
            except OSError: pass
            
            shutil.move(src, dst)
            os.chmod(dst, 0o444)  # Lock opponent's input.txt as read-only
            
    def _clean(self, text: str) -> str:
        out = text.strip()
        # Trim standard prefixes that LLMs frequently output
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


class PromptFactory:
    """Generates structured prompts and system directives for agents."""
    @staticmethod
    def build_instruction(agent_name: str, theme: str, is_first: bool = False) -> str:
        is_eng = LanguageDetector.is_english(theme)
        output_file = InputOutputController.OUTPUT_FILE
        input_file = InputOutputController.INPUT_FILE
        
        if is_eng:
            instruction_base = (
                f"When modifying files, edit ONLY '{output_file}' to write your opinion directly, completely in English.\n"
                f"[CRITICAL] Do NOT copy or quote the opponent's message (contents of '{input_file}') in your response. "
                f"Do NOT repeat your previous statements. Paraphrase your expressions and add new evidence to advance the discussion."
            )
            if is_first:
                return (
                    f"IMPORTANT: Read the discussion topic and write your opinion in '{output_file}'.\n"
                    f"{instruction_base}"
                )
            else:
                action = "opinions or perspectives to deepen the discussion" if agent_name == "a" else "counterarguments, agreements, or new perspectives"
                return (
                    f"IMPORTANT: The latest message from your opponent has been presented. Write your {action} in '{output_file}'.\n"
                    f"{instruction_base}"
                )
        else:
            instruction_base = (
                f"ファイルを編集する際は、必ず「{output_file}」のみを編集し、あなたの意見の本文のみを書き込んでください。\n"
                f"【厳重警告・繰り返し禁止】対話相手の発言（{input_file} の内容）をコピー・引用することは一切禁止します。\n"
                f"また、自分自身の過去の発言と全く同じ文章表現・語尾の重複を厳禁とし、異なる言い回しに完全にパラフレーズ（言い換え）した上で、必ず新しい論点や具体例を追加して記述してください。"
            )
            if is_first:
                return (
                    f"重要：提示された議論のテーマを読み、それに対するあなたの意見を {output_file} に書き込んでください。\n"
                    f"{instruction_base}"
                )
            else:
                action = "意見や議論を深める視点" if agent_name == "a" else "反論や同意、新たな視点"
                return (
                    f"重要：対話相手からの最新の意見が提示されました。これに対するあなたの{action}を {output_file} に書き込んでください。\n"
                    f"{instruction_base}"
                )


# ==============================================================================
# Discussion Orchestrator (Coordinator)
# ==============================================================================
class DiscussionCoordinator:
    """Manages the full orchestration and pipeline workflow of the multi-agent discussion."""
    def __init__(self, theme: str, model: str, max_rallies: int):
        self.theme = theme
        self.model = model
        self.max_rallies = max_rallies
        self.is_eng = LanguageDetector.is_english(theme)
        
        self.agent_a_config = AgentConfig("a", theme)
        self.agent_b_config = AgentConfig("b", theme)
        self.io_a = InputOutputController("a")
        self.io_b = InputOutputController("b")
        
        self.pane_a = None
        self.pane_b = None
        self.pane_tail = None
        
    def setup_environment(self):
        """Prepares discussion result files, configuration directories, and sandbox environments."""
        # 1. Initialize output markdown log file
        with open(CONVERSATION, 'w', encoding='utf-8') as f:
            f.write("# Aider Multi-Agent Discussion\n")
            if self.is_eng:
                f.write(f"## Topic: Autonomous AI Discussion on \"{self.theme}\"\n\n")
            else:
                f.write(f"## Topic: 「{self.theme}」についてのAI同士の自律ディスカッション\n\n")
                
        # 2. Setup config files (automatically generate if missing)
        self._prepare_configs()
        
        # 3. Clean up sandbox directories
        self._initialize_sandbox()
        
    def start_panes_and_aider(self):
        """Launches tmux panes and starts Aider processes inside them."""
        left_top = TmuxSession.run_command(['display-message', '-p', '#{pane_id}'])
        self.pane_a = TmuxSession.run_command(['split-window', '-h', '-t', left_top, '-P', '-F', '#{pane_id}'])
        self.pane_b = TmuxSession.run_command(['split-window', '-v', '-t', self.pane_a, '-P', '-F', '#{pane_id}'])
        self.pane_tail = TmuxSession.run_command(['split-window', '-v', '-t', left_top, '-P', '-F', '#{pane_id}'])
        
        time.sleep(2)
        
        # Start trailing conversation logs in tail pane
        TmuxSession.send_keys(self.pane_tail, f"tail -f {CONVERSATION}")
        
        # Restore agent config personas/manifestos in work sandboxes as AGENTS.md
        self.agent_a_config.restore()
        self.agent_b_config.restore()
        
        # Build Aider execution commands (explicitly read AGENTS.md using --read flag)
        aider_cmd_a = (
            f"aider --model {self.model} --no-git --no-auto-lint --yes-always --no-show-model-warnings --no-pretty "
            f"--read {InputOutputController.INPUT_FILE} --file {InputOutputController.OUTPUT_FILE} "
            "--read AGENTS.md "
            "--chat-history-file .aider.chat.history.md --input-history-file .aider.input.history "
            "--llm-history-file .aider.llm.history --no-restore-chat-history"
        )
        aider_cmd_b = (
            f"aider --model {self.model} --no-git --no-auto-lint --yes-always --no-show-model-warnings --no-pretty "
            f"--read {InputOutputController.INPUT_FILE} --file {InputOutputController.OUTPUT_FILE} "
            "--read AGENTS.md "
            "--chat-history-file .aider.chat.history.md --input-history-file .aider.input.history "
            "--llm-history-file .aider.llm.history --no-restore-chat-history"
        )
        
        TmuxSession.send_keys(self.pane_a, "cd sandbox/LeaderAI")
        TmuxSession.send_keys(self.pane_a, aider_cmd_a)
        
        TmuxSession.send_keys(self.pane_b, "cd sandbox/WorkerAI")
        TmuxSession.send_keys(self.pane_b, aider_cmd_b)
        
        print("Aider起動中（プロンプトの出現を待っています）...")
        TmuxSession.wait_for_prompt_stable(self.pane_a)
        TmuxSession.wait_for_prompt_stable(self.pane_b)
        print("Aider起動完了。設定ファイルはすべて読み込み専用（--read）で初期ロードされました。")
        
        # Debug display
        self._print_all_configs()
        
    def run_discussion(self):
        """Runs the main discussion loop between Agent A (Leader) and Agent B (Worker)."""
        # Ensure output.txt exists as size 0 cleanly to avoid Aider drop file error
        self.io_a.create_empty_output()
        prompt_a = PromptFactory.build_instruction("a", self.theme, is_first=True)
        print("Aider A に対話を開始します...")
        TmuxSession.send_keys(self.pane_a, prompt_a)
        
        for rally in range(1, self.max_rallies + 1):
            print(f"\n--- ラリー {rally} / {self.max_rallies} ---")
            
            # 1. Wait for LeaderAI (A) and fetch response
            TmuxSession.wait_for_prompt_stable(self.pane_a)
            response_a = self.io_a.read_output()
            
            with open(CONVERSATION, 'a', encoding='utf-8') as f:
                f.write(f"### Aider A\n\n{response_a}\n\n")
                
            # Move LeaderAI's output.txt directly to WorkerAI's input.txt
            self.io_a.move_to_opponent_input(self.io_b)
            
            # Re-create empty output.txt for B before prompting
            self.io_b.create_empty_output()
            
            # Refresh config files for B
            self.agent_b_config.restore()
            
            # Prompt B
            prompt_b = PromptFactory.build_instruction("b", self.theme)
            TmuxSession.send_keys(self.pane_b, prompt_b)
            
            # 2. Wait for WorkerAI (B) and fetch response
            TmuxSession.wait_for_prompt_stable(self.pane_b)
            response_b = self.io_b.read_output()
            
            with open(CONVERSATION, 'a', encoding='utf-8') as f:
                f.write(f"### Aider B\n\n{response_b}\n\n")
                
            # Move WorkerAI's output.txt directly to LeaderAI's input.txt
            self.io_b.move_to_opponent_input(self.io_a)
            
            # Re-create empty output.txt for A before prompting again
            self.io_a.create_empty_output()
            
            # Refresh config files for A
            self.agent_a_config.restore()
            
            # Loop next rally if not the end
            if rally < self.max_rallies:
                prompt_a = PromptFactory.build_instruction("a", self.theme)
                TmuxSession.send_keys(self.pane_a, prompt_a)
                
    def generate_summary(self):
        """Instructs a neutral LLM via direct Ollama API call using a temp script in the tail pane to compile a final summary."""
        print("\n--- ディスカッション完了。Aiderプロセスを終了し、要約の作成を開始します... ---")
        
        # 1. Shutdown Aider clients safely
        print("Aiderエージェントを終了しています...")
        TmuxSession.send_keys(self.pane_a, "/exit")
        TmuxSession.send_keys(self.pane_b, "/exit")
        time.sleep(3)  # Wait for Aider client shutdown
        
        # 2. Stop log trailing pane
        print("ログ監視（tail）を停止しています...")
        TmuxSession.send_keys(self.pane_tail, "C-c")
        time.sleep(1)  # Wait for shell prompt to return
        
        # Strip provider prefix to get bare Ollama model name (e.g. ollama_chat/gemma2:9b -> gemma2:9b)
        ollama_model = self.model.replace("ollama_chat/", "")
        
        # 3. Create a temporary helper python script to call Ollama API directly.
        # This completely avoids shell quoting and JSON escaping syntax errors on tmux command execution.
        temp_script_path = "temp_summary.py"
        temp_script_content = (
            "import urllib.request\n"
            "import json\n"
            "import sys\n\n"
            "def main():\n"
            "    theme = sys.argv[1]\n"
            "    is_eng = sys.argv[2] == 'True'\n"
            "    model = sys.argv[3]\n"
            "    log_file = sys.argv[4]\n\n"
            "    try:\n"
            "        with open(log_file, 'r', encoding='utf-8') as f:\n"
            "            conv_history = f.read()\n"
            "    except Exception as e:\n"
            "        sys.exit(f'Error reading {log_file}: {e}')\n\n"
            "    if is_eng:\n"
            "        summary_prompt = (\n"
            "            f'Please read the following discussion logs (full conversation history) carefully.\\n'\n"
            "            f'Analyze the debate objectively as a neutral moderator and write a summary (key disagreements, agreements) and a final conclusion in English.\\n'\n"
            "            f'Output ONLY the body of your summary. Do not output any greetings, markdown formatting (```), or prefaces.\\n\\n'\n"
            "            f'\"\"\"\\n{conv_history}\\n\"\"\"'\n"
            "        )\n"
            "    else:\n"
            "        summary_prompt = (\n"
            "            f'これまでの技術討論の全ログ（発言履歴）を慎重に読み、特定の立場に偏ることなく、客観的な第三者（中立のモデレーター）として以下の要点を整理し、日本語で要約および最終結論を作成してください。\\n'\n"
            "            f'1. 討論の主な論点と対立点\\n'\n"
            "            f'2. 両者が合意に至った、または歩み寄った点\\n'\n"
            "            f'3. 最終的な結論と今後の展望\\n'\n"
            "            f'挨拶、前置き、バックティック（```）によるマークダウンコードブロックは一切不要です。要約の本文のみを直接出力してください。\\n\\n'\n"
            "            f'\"\"\"\\n{conv_history}\\n\"\"\"'\n"
            "        )\n\n"
            "    url = 'http://localhost:11434/api/generate'\n"
            "    data = {\n"
            "        'model': model,\n"
            "        'prompt': summary_prompt,\n"
            "        'stream': False\n"
            "    }\n\n"
            "    try:\n"
            "        req = urllib.request.Request(\n"
            "            url, \n"
            "            data=json.dumps(data).encode('utf-8'), \n"
            "            headers={'Content-Type': 'application/json'}\n"
            "        )\n"
            "        with urllib.request.urlopen(req) as res:\n"
            "            response_text = json.loads(res.read().decode('utf-8'))['response']\n"
            "            sys.stdout.buffer.write(response_text.encode('utf-8'))\n"
            "    except Exception as e:\n"
            "        sys.exit(f'Error querying Ollama API: {e}')\n\n"
            "if __name__ == '__main__':\n"
            "    main()\n"
        )
        
        # Write the temporary script to root
        with open(temp_script_path, 'w', encoding='utf-8') as f:
            f.write(temp_script_content)
            
        print("中立のAI（Ollama）を起動し、要約を作成しています...")
        # Write section divider header first
        with open(CONVERSATION, 'a', encoding='utf-8') as f:
            if self.is_eng:
                f.write("\n## Discussion Summary and Final Conclusion\n\n")
            else:
                f.write("\n## 議論の要約と最終結論\n\n")
                
        # 5. Execute the temporary script via pane_tail redirecting stdout to CONVERSATION
        run_cmd = f"python3 {temp_script_path} \"{self.theme}\" \"{self.is_eng}\" \"{ollama_model}\" \"{CONVERSATION}\" >> {CONVERSATION}"
        TmuxSession.send_keys(self.pane_tail, run_cmd)
        
        # Wait for the python execution to finish and shell prompt to return stable
        TmuxSession.wait_for_prompt_stable(self.pane_tail)
        
        # 6. Cleanup temporary script
        if os.path.exists(temp_script_path):
            try: os.remove(temp_script_path)
            except OSError: pass
            
        print(f"要約と最終結論が {CONVERSATION} に追記されました。")
        
        # 7. Display the entire final discussion log in the tail pane for visibility
        print("最終ディスカッションログを表示します...")
        TmuxSession.send_keys(self.pane_tail, f"cat {CONVERSATION}")
        TmuxSession.wait_for_prompt_stable(self.pane_tail)
        
    def shutdown(self):
        """Final cleanup of the discussion environment."""
        print("ディスカッション環境を終了します。")
        
    def _prepare_configs(self):
        os.makedirs("agent_configs", exist_ok=True)
        # Migrate old root-level configs if present
        for f_name in ["persona_a.txt", "manifest_a.txt", "persona_b.txt", "manifest_b.txt"]:
            if os.path.exists(f_name) and not os.path.exists(os.path.join("agent_configs", f_name)):
                shutil.move(f_name, os.path.join("agent_configs", f_name))
                print(f"設定ファイルを agent_configs/ に移行しました: {f_name}")
                
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

    def _initialize_sandbox(self):
        for dir_name in ["sandbox/LeaderAI", "sandbox/WorkerAI"]:
            os.makedirs(dir_name, exist_ok=True)
            for cache_file in [".aider.chat.history.md", ".aider.input.history", ".aider.llm.history", "AGENTS.md", "output.txt", "input.txt"]:
                path = os.path.join(dir_name, cache_file)
                if os.path.exists(path):
                    try:
                        os.chmod(path, 0o644)
                        os.remove(path)
                    except OSError: pass
            cache_dir = os.path.join(dir_name, ".aider.tags.cache.v4")
            if os.path.exists(cache_dir):
                try: shutil.rmtree(cache_dir)
                except OSError: pass
                
        # Initialize default placeholder inputs using raw write
        initial_msg_a = "Discussion started: Please state your first opinion." if self.is_eng else "（ディスカッション開始：最初の意見を述べてください）"
        initial_msg_b = "Waiting for the opponent to start the discussion..." if self.is_eng else "（対話相手の開始をお待ちください）"
        
        self.io_a.write_raw_input(initial_msg_a)
        self.io_b.write_raw_input(initial_msg_b)
        
    def _print_all_configs(self):
        # Display config summaries in main terminal pane
        print_file_content("Aider A AGENTS.md", "sandbox/LeaderAI/AGENTS.md")
        print_file_content("Aider B AGENTS.md", "sandbox/WorkerAI/AGENTS.md")


def print_file_content(label, filepath):
    if not os.path.exists(filepath):
        return
    print(f"\n=== {label} ({filepath}) ===")
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            print(f.read().strip())
    except Exception as e:
        print(f"(Error reading file: {e})")
    print("=" * (len(label) + len(filepath) + 7) + "\n")


# ==============================================================================
# Executable Entrypoint
# ==============================================================================
def main():
    coordinator = DiscussionCoordinator(THEME, MODEL, MAX_RALLIES)
    try:
        coordinator.setup_environment()
        coordinator.start_panes_and_aider()
        coordinator.run_discussion()
        coordinator.generate_summary()
    finally:
        coordinator.shutdown()

if __name__ == '__main__':
    main()
