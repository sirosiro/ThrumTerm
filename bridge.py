#!/usr/bin/env encoding=utf-8 python3
import sys
import os
import time
import subprocess
import shutil

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
            # Check if the last line ends with prompt character '>'
            if len(lines) >= 1 and lines[-1].strip() == '>':
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
        # Instruct agents to reply directly via chat stdout rather than modifying output.txt files
        combined_content += "\n\n"
        if self.is_eng:
            combined_content += (
                "[CRITICAL CONVENTIONS / RULES]\n"
                "1. State your opinion directly in the chat response. Do NOT output markdown code blocks (```) or greetings.\n"
                "2. Do NOT copy the opponent's message or repeat the same points. Focus on presenting new perspectives or counterarguments.\n"
                "3. Deeply ponder the opponent's message and your assigned role before developing your next opinion."
            )
        else:
            combined_content += (
                "【絶対厳守のコーディング・出力ルール】\n"
                "1. あなたの意見はチャットの応答として直接述べてください。マークダウンコードブロック（```）による囲みや挨拶は不要です。\n"
                "2. 対話相手の発言をコピー（オウム返し）したり、同じ主張を繰り返さないでください。常に新しい視点や具体的な反論を追加してください。\n"
                "3. 対話相手の意見と与えられた役割を深く熟考した上で、次の意見や反論を展開してください。"
            )
                
        # Write merged file to destination
        with open(agents_md_dest, 'w', encoding='utf-8') as f:
            f.write(combined_content)
            
        # Lock destination as read-only (chmod 444) to prevent LLM modification
        os.chmod(agents_md_dest, 0o444)


class ResponseExtractor:
    """Extracts the agent's pure text response from the tmux terminal window output buffer."""
    MSG_START_MARKER = "===MSG_START==="

    @classmethod
    def extract(cls, pane_id: str) -> str:
        # Capture the pane buffer including 100 lines scrollback
        output = TmuxSession.run_command(['capture-pane', '-pt', pane_id, '-S', '-100'])
        lines = output.splitlines()
        
        # Locate the last occurrence of the message marker in reverse order
        start_idx = -1
        for i in range(len(lines) - 1, -1, -1):
            if cls.MSG_START_MARKER in lines[i]:
                start_idx = i
                break
                
        if start_idx == -1:
            return ""
            
        # Collect response lines following the marker until the final wait prompt
        result_lines = []
        for i in range(start_idx + 1, len(lines)):
            line = lines[i].strip()
            
            # Skip Aider shell prompt lines and system statistics
            if line == '>':
                continue
            if line.startswith('Tokens:') or line.startswith('> Tokens:'):
                continue
            if 'Applied edit to' in line or 'Create new file?' in line:
                continue
            if line.startswith('>') and i == len(lines) - 1:
                continue
                
            result_lines.append(lines[i])
            
        raw_response = "\n".join(result_lines).strip()
        return cls._clean(raw_response)

    @staticmethod
    def _clean(text: str) -> str:
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
        
        if is_eng:
            if is_first:
                return (
                    f"Topic: \"{theme}\"\n"
                    f"Please state your first opinion on this topic directly as a chat response. Do not use greetings."
                )
            else:
                action = "opinion or perspective to deepen the discussion" if agent_name == "a" else "counterargument, agreement, or new perspective"
                return (
                    f"Opponent's opinion presented. Please state your {action} directly as a chat response. Do not repeat the opponent's words."
                )
        else:
            if is_first:
                return (
                    f"議論のテーマは「{theme}」です。\n"
                    f"これに対するあなたの最初の意見をチャットの応答として直接述べてください。挨拶や余計な前置きは不要です。"
                )
            else:
                action = "意見や議論を深める視点" if agent_name == "a" else "反論や同意、新たな視点"
                return (
                    f"対話相手からの意見が提示されました。\n"
                    f"これに対するあなたの{action}をチャットの応答として直接述べてください。相手の言葉をそのまま繰り返さないでください。"
                )

    @staticmethod
    def build_summary_instruction(theme: str) -> str:
        is_eng = LanguageDetector.is_english(theme)
        
        if is_eng:
            return (
                f"IMPORTANT: Read the discussion logs (full conversation history) carefully.\n"
                f"Summarize the discussion objectively (main points of disagreement and agreement) and write the final conclusion directly as a chat response.\n"
                f"No extra greetings or explanations are needed."
            )
        else:
            return (
                f"重要：提示されたディスカッションのログ（全発言履歴）を慎重に読み、これまでの議論の客観的な要約（主な対立点や合意点）および最終的な結論をまとめ、チャットの応答として直接述べてください。\n"
                f"余計な挨拶や説明は一切不要です。"
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
        
        # Build Aider execution commands (Aider is run as a pure chat client without --file flags)
        aider_cmd_a = (
            f"aider --model {self.model} --no-git --no-auto-lint --yes-always --no-show-model-warnings --no-pretty "
            "--read AGENTS.md "
            "--chat-history-file .aider.chat.history.md --input-history-file .aider.input.history "
            "--llm-history-file .aider.llm.history --no-restore-chat-history"
        )
        aider_cmd_b = (
            f"aider --model {self.model} --no-git --no-auto-lint --yes-always --no-show-model-warnings --no-pretty "
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
        prompt_a = PromptFactory.build_instruction("a", self.theme, is_first=True)
        print("Aider A に対話を開始します...")
        self._send_prompt_with_marker(self.pane_a, prompt_a)
        
        for rally in range(1, self.max_rallies + 1):
            print(f"\n--- ラリー {rally} / {self.max_rallies} ---")
            
            # 1. Wait for LeaderAI (A) and extract response from screen buffer
            TmuxSession.wait_for_prompt_stable(self.pane_a)
            response_a = ResponseExtractor.extract(self.pane_a)
            
            with open(CONVERSATION, 'a', encoding='utf-8') as f:
                f.write(f"### Aider A\n\n{response_a}\n\n")
                
            # Refresh config files for B
            self.agent_b_config.restore()
            
            # Prompt B with A's response directly
            prompt_b = f"対話相手（Aider A）の発言は以下の通りです：\n「{response_a}」\n\n" + PromptFactory.build_instruction("b", self.theme)
            self._send_prompt_with_marker(self.pane_b, prompt_b)
            
            # 2. Wait for WorkerAI (B) and extract response from screen buffer
            TmuxSession.wait_for_prompt_stable(self.pane_b)
            response_b = ResponseExtractor.extract(self.pane_b)
            
            with open(CONVERSATION, 'a', encoding='utf-8') as f:
                f.write(f"### Aider B\n\n{response_b}\n\n")
                
            # Refresh config files for A
            self.agent_a_config.restore()
            
            # Loop next rally if not the end
            if rally < self.max_rallies:
                prompt_a = f"対話相手（Aider B）の発言は以下の通りです：\n「{response_b}」\n\n" + PromptFactory.build_instruction("a", self.theme)
                self._send_prompt_with_marker(self.pane_a, prompt_a)
                
    def generate_summary(self):
        """Instructs Agent A to read the discussion log and compile a final summary."""
        print("\n--- ディスカッション完了。議論の要約と最終結論を作成中... ---")
        
        with open(CONVERSATION, 'r', encoding='utf-8') as f:
            conv_history = f.read()
            
        summary_prompt = f"これまでの会話ログ（全発言履歴）は以下の通りです：\n\n\"\"\"\n{conv_history}\n\"\"\"\n\n" + PromptFactory.build_summary_instruction(self.theme)
        self._send_prompt_with_marker(self.pane_a, summary_prompt)
        
        TmuxSession.wait_for_prompt_stable(self.pane_a)
        summary_response = ResponseExtractor.extract(self.pane_a)
        
        with open(CONVERSATION, 'a', encoding='utf-8') as f:
            if self.is_eng:
                f.write(f"## Discussion Summary and Final Conclusion\n\n{summary_response}\n\n")
            else:
                f.write(f"## 議論の要約と最終結論\n\n{summary_response}\n\n")
                
        print("要約と最終結論が discussion_log.md に追記されました。")
        
    def shutdown(self):
        """Sends exit command to stop Aider client processes clean."""
        print("Aiderエージェントを終了しています...")
        TmuxSession.send_keys(self.pane_a, "/exit")
        TmuxSession.send_keys(self.pane_b, "/exit")
        print("ディスカッション環境を終了します。")
        
    def _send_prompt_with_marker(self, pane_id: str, prompt_text: str):
        # Embed message start marker to cleanly capture prompt boundaries
        full_keys = f"{ResponseExtractor.MSG_START_MARKER}\n{prompt_text}"
        TmuxSession.send_keys(pane_id, full_keys)

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
