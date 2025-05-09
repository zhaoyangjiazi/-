from flask import Flask, request, jsonify, send_from_directory
import os
import subprocess
import glob
from datetime import datetime
try:
    import markdown
except ImportError:
    print("markdown模块未安装，尝试自动安装...")
    try:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "markdown"])
        import markdown
        print("markdown模块安装成功")
    except Exception as e:
        print(f"安装markdown模块失败: {str(e)}")
        # 提供一个简易的markdown到HTML转换函数作为后备方案
        def simple_markdown_to_html(text):
            """简单的markdown转HTML函数，用于markdown模块不可用时"""
            # 处理标题
            text = re.sub(r'^# (.*?)$', r'<h1>\1</h1>', text, flags=re.MULTILINE)
            text = re.sub(r'^## (.*?)$', r'<h2>\1</h2>', text, flags=re.MULTILINE)
            text = re.sub(r'^### (.*?)$', r'<h3>\1</h3>', text, flags=re.MULTILINE)
            
            # 处理强调
            text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)
            text = re.sub(r'\*(.*?)\*', r'<em>\1</em>', text)
            
            # 处理链接和图片
            text = re.sub(r'!\[(.*?)\]\((.*?)\)', r'<img src="\2" alt="\1">', text)
            text = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2">\1</a>', text)
            
            # 处理分隔线
            text = re.sub(r'^---$', r'<hr>', text, flags=re.MULTILINE)
            
            # 处理段落和换行
            paragraphs = text.split('\n\n')
            for i, p in enumerate(paragraphs):
                if not p.startswith('<h') and not p.startswith('<hr'):
                    paragraphs[i] = f'<p>{p}</p>'
            
            return '\n'.join(paragraphs)
        
        # 替换markdown.markdown函数
        def markdown_fallback(text):
            return simple_markdown_to_html(text)
        
        markdown = type('markdown', (), {'markdown': markdown_fallback})
        print("使用简易markdown转换后备方案")
import time
from pathlib import Path
import re
from dotenv import load_dotenv
import requests
import uuid
import json
import base64
import sys

app = Flask(__name__, static_folder='.')

# 添加额外的静态文件夹映射，确保生成的图片可以被直接访问
@app.route('/generated_images/<path:filename>')
def generated_images(filename):
    return send_from_directory('generated_images', filename)

@app.route('/')
def index():
    return send_from_directory('.', 'ui.html')

@app.route('/new')
def new_ui():
    return send_from_directory('.', 'ui_new.html')

@app.route('/generate_story', methods=['POST'])
def generate_story():
    try:
        # 获取前端发送的故事主题和语言选择
        data = request.json
        theme = data.get('theme', '')
        language = data.get('language', 'zh')  # 默认中文
        
        # 获取用户自定义禁用词
        custom_forbidden_words = data.get('forbidden_words', '')
        
        if not theme:
            return jsonify({"error": "主题不能为空"}), 400
        
        # 输出调试信息
        print(f"正在处理{language}故事请求，主题: {theme}")
        
        # 检查是否已有该主题的故事文件
        story_dir = 'generated_stories'
        os.makedirs(story_dir, exist_ok=True)
        
        # 尝试查找包含主题名的已有文件
        theme_specific_pattern = f"*{theme}*.md"
        existing_theme_files = glob.glob(os.path.join(story_dir, theme_specific_pattern))
        
        if existing_theme_files:
            print(f"找到已有的主题相关文件: {existing_theme_files}")
            # 使用最新的文件
            latest_story = max(existing_theme_files, key=os.path.getmtime)
            print(f"使用已有故事文件: {latest_story}")
            
            # 读取故事文件内容
            try:
                with open(latest_story, 'r', encoding='utf-8') as f:
                    story_content = f.read()
                    
                if story_content.strip():
                    # 将Markdown内容转换为HTML
                    html_content = markdown.markdown(story_content)
                    
                    # 查找相关图片
                    story_basename = os.path.basename(latest_story).split('_')[0]
                    image_files = glob.glob(os.path.join('generated_images', f"{story_basename}*.png"))
                    
                    # 如果没有找到匹配的图片，尝试使用主题关键词
                    if not image_files:
                        image_files = glob.glob(os.path.join('generated_images', f"*{theme}*.png"))
                    
                    image_urls = [f"/view_image?path={img}" for img in image_files]
                    print(f"找到相关图片: {len(image_urls)}个")
                    
                    # 准备生成语音所需的纯文本内容
                    plain_text = extract_plain_text(story_content)
                    
                    # 返回已有的故事结果给前端
                    return jsonify({
                        "text": html_content,
                        "images": image_urls,
                        "markdown_url": f"/download?path={latest_story}",
                        "raw_markdown": story_content,
                        "plain_text": plain_text,
                        "is_cached": True
                    })
            except Exception as e:
                print(f"读取已有故事文件失败: {str(e)}，将生成新故事")
                # 如果读取已有文件失败，继续生成新故事
        
        # 更新.env文件中的OUTPUT_LANG设置
        update_env_setting('OUTPUT_LANG', language)
        
        # 如果用户提供了自定义禁用词，更新环境变量
        if custom_forbidden_words:
            # 获取当前的禁用词列表
            current_forbidden = os.getenv("FORBIDDEN_KEYWORDS", "nsfw,ugly,scary,horror,violent,blood,gore,disturbing")
            
            # 处理用户输入的禁用词（按逗号或空格分隔）
            user_words = [word.strip() for word in re.split(r'[,\s]+', custom_forbidden_words) if word.strip()]
            
            # 合并现有禁用词和用户自定义禁用词
            all_words = set(current_forbidden.split(','))
            all_words.update(user_words)
            
            # 更新环境变量
            new_forbidden_words = ','.join(all_words)
            update_env_setting('FORBIDDEN_KEYWORDS', new_forbidden_words)
            print(f"已更新禁用词列表: {new_forbidden_words}")
        
        # 将主题写入到test.md文件
        with open('test.md', 'w', encoding='utf-8') as f:
            f.write(theme)
        
        # 记录开始处理的时间
        process_start_time = datetime.now()
        
        # 记录当前已有的故事文件
        story_files_before = set(glob.glob(os.path.join(story_dir, '*.md')))
        print(f"当前共有 {len(story_files_before)} 个故事文件")
        
        # 简单运行故事生成脚本，不需要检查其运行状态
        script_path = 'story_generator_V2.py'
        if not os.path.exists(script_path):
            # 尝试查找脚本的绝对路径
            possible_paths = [
                os.path.join(os.path.dirname(os.path.abspath(__file__)), 'story_generator_V2.py'),
                os.path.join(os.getcwd(), 'story_generator_V2.py'),
                'C:\\Users\\86182\\Desktop\\Picture_book_production-main\\story_generator_V2.py'  # 保留原始路径作为后备
            ]
            
            for path in possible_paths:
                if os.path.exists(path):
                    script_path = path
                    break
        
        if not os.path.exists(script_path):
            raise FileNotFoundError(f"无法找到故事生成脚本: story_generator_V2.py")
            
        print(f"开始运行故事生成脚本: {script_path}")
        # 以非阻塞方式运行脚本，不关心其输出
        subprocess.Popen([sys.executable, script_path])
        print("脚本已启动，开始等待故事文件生成")
        
        # 主动检查是否有新文件生成，最多等待45分钟
        max_wait_time = 2700  # 45分钟
        start_time = time.time()
        new_file_found = False
        new_story_file = None
        
        print(f"开始检查故事文件，最长等待时间: {max_wait_time}秒")
        
        while time.time() - start_time < max_wait_time:
            # 每5秒检查一次
            time.sleep(5)
            
            # 获取当前所有故事文件
            current_files = set(glob.glob(os.path.join(story_dir, '*.md')))
            
            # 检查是否有新文件生成
            if len(current_files) > len(story_files_before):
                print("检测到新文件生成")
                # 找出新增的文件
                new_files = list(current_files - story_files_before)
                if new_files:
                    new_story_file = max(new_files, key=os.path.getmtime)
                    new_file_found = True
                    break
            
            # 尝试查找包含主题名的文件
            theme_files = glob.glob(os.path.join(story_dir, theme_specific_pattern))
            for file in theme_files:
                # 如果文件不在初始列表中或修改时间晚于处理开始时间
                if file not in story_files_before or datetime.fromtimestamp(os.path.getmtime(file)) > process_start_time:
                    print(f"找到与主题相关的新文件: {file}")
                    new_story_file = file
                    new_file_found = True
                    break
            
            if new_file_found:
                break
                
            # 每60秒打印一次等待进度
            elapsed = time.time() - start_time
            if int(elapsed) % 60 == 0:
                print(f"已等待 {int(elapsed/60)} 分钟，继续等待故事生成...")
        
        if not new_file_found:
            print("等待超时，未检测到新故事文件生成")
            # 尝试一次查找任何包含主题名的文件，即使它不是新的
            theme_files = glob.glob(os.path.join(story_dir, theme_specific_pattern))
            if theme_files:
                new_story_file = max(theme_files, key=os.path.getmtime)
                print(f"找到与主题相关的最新文件（可能不是新生成的）: {new_story_file}")
            else:
                return jsonify({"error": "故事生成超时，请稍后重试"}), 504  # 使用504网关超时错误
        
        # 如果找到了新文件，直接使用它
        if new_story_file:
            latest_story = new_story_file
            print(f"找到新生成的故事文件: {latest_story}")
        else:
            # 获取生成的最新故事文件
            story_files = glob.glob(os.path.join(story_dir, '*.md'))
            if not story_files:
                print("未找到任何故事文件")
                return jsonify({"error": "没有找到生成的故事文件"}), 500
            
            # 按照修改时间排序，获取最新的文件
            latest_story = max(story_files, key=os.path.getmtime)
            print(f"找到最新故事文件: {latest_story}")
        
        # 读取故事文件内容
        try:
            with open(latest_story, 'r', encoding='utf-8') as f:
                story_content = f.read()
                
            if not story_content.strip():
                print(f"警告：故事文件 {latest_story} 内容为空")
                return jsonify({"error": "生成的故事内容为空"}), 500
        except Exception as e:
            print(f"读取故事文件时发生错误: {str(e)}")
            return jsonify({"error": f"无法读取故事文件: {str(e)}"}), 500
        
        # 获取相关的图片文件路径
        # 首先尝试用文件名前缀匹配，如果没有结果，则尝试用主题关键词匹配
        story_basename = os.path.basename(latest_story).split('_')[0]
        image_files = glob.glob(os.path.join('generated_images', f"{story_basename}*.png"))
        
        # 如果没有找到匹配的图片，尝试使用主题关键词
        if not image_files:
            image_files = glob.glob(os.path.join('generated_images', f"*{theme}*.png"))
        
        # 创建图片URL字典，方便后续根据图片名称引用
        image_url_dict = {}
        for img in image_files:
            img_basename = os.path.basename(img)
            # 使用绝对文件路径而不是URL路径
            abs_path = os.path.abspath(img)
            image_url_dict[img_basename] = abs_path
        
        print(f"找到相关图片: {len(image_url_dict)}个")
        
        # 准备生成语音所需的纯文本内容(移除Markdown标记)
        plain_text = extract_plain_text(story_content)
        
        # 使用自定义处理而不是直接使用markdown模块，确保图片和文字正确交替显示
        html_content = process_markdown_with_images(story_content, image_url_dict)
        
        # 返回结果给前端
        return jsonify({
            "text": html_content,
            "images": list(image_url_dict.values()),
            "markdown_url": f"/download?path={latest_story}",
            "raw_markdown": story_content,
            "plain_text": plain_text,
            "is_cached": False
        })
        
    except Exception as e:
        error_message = str(e)
        print(f"生成故事时发生错误: {error_message}")
        return jsonify({"error": f"处理请求时发生错误: {error_message}"}), 500

@app.route('/generate_audio', methods=['POST'])
def generate_audio():
    try:
        # 获取要转换为语音的文本
        data = request.json
        text = data.get('text', '')
        language = data.get('language', 'zh')
        
        if not text:
            return jsonify({"error": "文本不能为空"}), 400
        
        print(f"收到语音生成请求，文本长度: {len(text)}")
        
        # 从文本中去除图片信息
        # 移除所有的图片Markdown标记
        text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
        
        print(f"处理后的文本长度: {len(text)}")
        
        # 测试百度API连接
        try:
            test_response = requests.get("https://aip.baidubce.com/oauth/2.0/token", timeout=5)
            print(f"百度API连接测试: {test_response.status_code}")
        except Exception as e:
            print(f"无法连接到百度API服务器: {str(e)}")
            return jsonify({"error": "无法连接到百度API服务器，请检查网络连接"}), 500
        
        # 确保音频目录存在
        audio_dir = os.path.join(os.getcwd(), 'generated_audio')
        os.makedirs(audio_dir, exist_ok=True)
        
        # 生成唯一的文件名
        audio_filename = f"story_audio_{uuid.uuid4()}.mp3"
        audio_path = os.path.join(audio_dir, audio_filename)
        
        print(f"准备调用百度语音合成API，语言: {language}")
        
        # 使用百度语音合成服务生成语音
        success = generate_speech_baidu(text, audio_path, language)
        
        if not success:
            # 尝试使用文件中的内容
            print("API调用失败，尝试从故事文件中获取纯文本")
            
            # 查找最新的故事文件
            story_dir = 'generated_stories'
            story_files = glob.glob(os.path.join(story_dir, '*.md'))
            
            if story_files:
                latest_story = max(story_files, key=os.path.getmtime)
                print(f"找到最新故事文件: {latest_story}")
                
                # 读取故事文件内容
                with open(latest_story, 'r', encoding='utf-8') as f:
                    story_content = f.read()
                
                # 提取纯文本，去除所有Markdown标记和图片信息
                pure_text = extract_plain_text(story_content)
                
                print(f"从文件中提取的纯文本长度: {len(pure_text)}")
                
                # 再次尝试生成语音
                success = generate_speech_baidu(pure_text, audio_path, language)
                
                if not success:
                    # 检查百度API密钥
                    api_key = os.getenv('BAIDU_API_KEY', '')
                    secret_key = os.getenv('BAIDU_SECRET_KEY', '')
                    if not api_key or not secret_key:
                        return jsonify({"error": "百度API密钥未设置，请在.env文件中配置BAIDU_API_KEY和BAIDU_SECRET_KEY"}), 500
                    return jsonify({"error": "语音生成失败，请检查百度API配置、网络连接和服务器日志"}), 500
            else:
                return jsonify({"error": "未找到故事文件"}), 500
        
        # 返回音频文件的URL
        return jsonify({
            "audio_url": f"/audio/{audio_filename}"
        })
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"生成语音时发生错误: {str(e)}")
        print(f"详细错误信息: {error_details}")
        return jsonify({"error": f"生成语音时发生错误: {str(e)}"}), 500

@app.route('/audio/<filename>')
def serve_audio(filename):
    return send_from_directory('generated_audio', filename)

def update_env_setting(key, value):
    """更新.env文件中的特定设置"""
    env_path = '.env'
    
    # 读取当前.env文件内容
    with open(env_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 使用正则表达式匹配并替换设置
    pattern = re.compile(f"^{key}=.*$", re.MULTILINE)
    if pattern.search(content):
        # 如果设置已存在，替换它
        new_content = pattern.sub(f"{key}={value}", content)
    else:
        # 如果设置不存在，添加到文件末尾
        new_content = content + f"\n{key}={value}"
    
    # 写回文件
    with open(env_path, 'w', encoding='utf-8') as f:
        f.write(new_content)

def extract_plain_text(markdown_content):
    """从Markdown文本中提取纯文本内容"""
    # 移除标题标记
    text = re.sub(r'#+\s+', '', markdown_content)
    # 移除图片链接
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
    # 移除链接 - 修复这里的正则表达式错误
    text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text)
    # 移除强调标记
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    # 移除代码块
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    # 移除水平线
    text = re.sub(r'---', '', text)
    # 移除其他Markdown元素
    text = text.replace('- ', '')
    
    # 清理多余的空行
    text = re.sub(r'\n\s*\n', '\n\n', text)
    
    return text.strip()

def get_baidu_token():
    """
    获取百度语音服务的访问令牌
    
    根据百度云文档：https://cloud.baidu.com/doc/SPEECH/s/Em8snejw1
    """
    # 从环境变量获取API密钥
    api_key = os.getenv('BAIDU_API_KEY', '').strip()
    secret_key = os.getenv('BAIDU_SECRET_KEY', '').strip()
    
    if not api_key or not secret_key:
        print("错误：未找到百度API密钥配置，请在.env文件中设置BAIDU_API_KEY和BAIDU_SECRET_KEY")
        return None
    
    # 根据官方文档构建token请求
    token_url = "https://aip.baidubce.com/oauth/2.0/token"
    
    try:
        # 准备请求参数
        params = {
            'grant_type': 'client_credentials',
            'client_id': api_key,
            'client_secret': secret_key
        }
        
        print(f"正在请求百度访问令牌，参数: {params}")
        
        # 发送POST请求 - 使用params参数而不是URL拼接
        response = requests.post(token_url, params=params)
        
        print(f"百度访问令牌响应状态码: {response.status_code}")
        print(f"响应内容: {response.text}")
        
        if response.status_code != 200:
            print(f"获取token失败，状态码: {response.status_code}")
            return None
        
        try:
            result = response.json()
            
            if 'access_token' in result:
                print(f"成功获取百度访问令牌: {result['access_token']}")
                return result['access_token']
            else:
                print(f"获取百度token失败: {result}")
                return None
        except ValueError:
            print(f"解析JSON响应失败，响应内容: {response.text[:200]}")
            return None
            
    except Exception as e:
        print(f"获取百度token发生错误: {str(e)}")
        import traceback
        print(f"详细错误: {traceback.format_exc()}")
        return None

def generate_speech_baidu(text, output_path, language='zh'):
    """
    使用百度长文本在线合成服务生成语音文件
    
    参数:
        text: 需要转换的文本
        output_path: 输出音频文件路径
        language: 语言代码，'zh'为中文，'en'为英文
        
    文档参考：https://cloud.baidu.com/doc/SPEECH/s/ulbxh8rbu
    """
    try:
        # 获取百度访问令牌
        token = get_baidu_token()
        if not token:
            print("未能获取百度访问令牌，请检查API密钥配置")
            return False
        
        print(f"成功获取百度访问令牌，准备调用语音合成API")
        
        # 首先尝试长文本合成API
        print("尝试使用长文本合成API")
        
        # 长文本合成API接口URL (create)
        create_url = "https://aip.baidubce.com/rpc/2.0/tts/v1/create"
        
        # 准备请求头
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        
        # 准备请求参数
        # 注意：如果文本超过10000字符，需要截断
        if len(text) > 10000:
            print(f"文本长度({len(text)})超过10000字符限制，将截断")
            text = text[:10000]
        
        # 创建合成任务
        # 参数说明参考: https://cloud.baidu.com/doc/SPEECH/s/ulbxh8rbu
        create_payload = {
            "text": text,
            "format": "mp3-16k",  # 百度支持的格式: mp3-16k, mp3-48k, wav-8k, wav-16k 等
            "voice": 0,       # 发音人: 0-普通女声，1-普通男声，3-情感男声，4-情感女声
            "lang": "zh" if language == 'zh' else "en",  # 语言，zh/en
            "speed": 5,       # 语速，取值0-15，默认为5中语速
            "pitch": 5,       # 音调，取值0-15，默认为5中音调
            "volume": 5,      # 音量，取值0-15，默认为5中音量
            "enable_subtitle": 0  # 是否开启字幕，0-关闭，1-中文，2-英文，3-中英
        }
        
        print(f"创建任务参数: {create_payload}")
        
        # 发送创建请求
        print("发送创建长文本合成任务请求")
        create_response = requests.post(
            f"{create_url}?access_token={token}", 
            headers=headers, 
            json=create_payload
        )
        
        print(f"创建任务响应状态码: {create_response.status_code}")
        
        try:
            create_result = create_response.json()
            print(f"创建任务响应: {create_result}")
            
            # 检查是否有错误
            if 'error_code' in create_result:
                error_code = create_result['error_code']
                error_msg = create_result.get('error_msg', '未知错误')
                print(f"创建任务失败: 错误码 {error_code}, 错误信息: {error_msg}")
                if 'Access token invalid or no longer valid' in error_msg:
                    # 尝试删除token缓存，下次重新获取
                    try:
                        if os.path.exists('.token_cache.json'):
                            os.remove('.token_cache.json')
                            print("已删除token缓存，下次将重新获取")
                    except:
                        pass
                # 如果是任务创建失败，不要继续尝试查询
                return False
                
            # 获取任务ID
            task_id = create_result.get('task_id')
            if not task_id:
                print("未返回任务ID")
                return False
                
            print(f"成功创建合成任务，任务ID: {task_id}")
            
            # 查询任务API
            query_url = "https://aip.baidubce.com/rpc/2.0/tts/v1/query"
            
            # 轮询查询任务状态
            max_retries = 30  # 最多查询30次
            retry_interval = 3  # 每次间隔3秒
            
            for i in range(max_retries):
                print(f"第{i+1}次查询任务状态...")
                
                # 构建查询请求
                query_payload = {
                    "task_ids": [task_id]
                }
                
                # 发送查询请求
                query_response = requests.post(
                    f"{query_url}?access_token={token}", 
                    headers=headers, 
                    json=query_payload
                )
                
                print(f"查询响应状态码: {query_response.status_code}")
                
                try:
                    query_result = query_response.json()
                    print(f"查询响应: {query_result}")
                    
                    # 检查是否有错误
                    if 'error_code' in query_result:
                        error_code = query_result['error_code']
                        error_msg = query_result.get('error_msg', '未知错误')
                        print(f"查询任务失败: 错误码 {error_code}, 错误信息: {error_msg}")
                        break
                        
                    # 解析任务信息
                    tasks_info = query_result.get('tasks_info', [])
                    if not tasks_info:
                        print("未返回任务信息")
                        break
                        
                    # 获取第一个任务的状态
                    task_info = tasks_info[0]
                    task_status = task_info.get('task_status')
                    
                    if task_status == 'Created':
                        print("任务已创建，等待处理...")
                    elif task_status == 'Running':
                        print("任务正在处理中...")
                    elif task_status == 'Success':
                        print("任务处理成功")
                        
                        # 获取语音URL
                        task_result = task_info.get('task_result', {})
                        speech_url = task_result.get('speech_url')
                        
                        if speech_url:
                            print(f"获取到语音URL: {speech_url}")
                            
                            # 下载语音文件
                            print(f"正在下载语音文件...")
                            speech_response = requests.get(speech_url)
                            
                            if speech_response.status_code == 200:
                                with open(output_path, 'wb') as f:
                                    f.write(speech_response.content)
                                print(f"语音文件已保存到: {output_path}")
                                return True
                            else:
                                print(f"下载语音文件失败，状态码: {speech_response.status_code}")
                                print(f"响应内容: {speech_response.text[:200]}")
                        else:
                            print("未返回语音URL")
                        
                        # 无论是否下载成功，任务已完成，退出轮询
                        break
                    elif task_status == 'Failed':
                        task_result = task_info.get('task_result', {})
                        error_code = task_result.get('error_code')
                        error_msg = task_result.get('error_msg', '未知错误')
                        print(f"任务处理失败: 错误码 {error_code}, 错误信息: {error_msg}")
                        break
                    else:
                        print(f"未知任务状态: {task_status}")
                        break
                except ValueError:
                    print(f"解析查询响应失败，响应内容: {query_response.text[:200]}")
                    break
                    
                # 如果任务未完成，等待一段时间后再次查询
                time.sleep(retry_interval)
                
            # 到这里意味着长文本合成失败或轮询超时，尝试短文本合成
            print("长文本合成失败或超时，尝试使用短文本合成API")
            
        except ValueError:
            print(f"解析创建任务响应失败，响应内容: {create_response.text[:200]}")
            # 创建任务失败，直接尝试短文本合成
        
        # 如果长文本合成失败，回退到短文本合成API
        print("开始使用短文本合成API")
        short_text_url = "https://tsn.baidu.com/text2audio"
        
        # 如果文本太长，分段处理
        max_length = 500  # 短文本API单次请求的文本长度限制
        text_parts = [text[i:i+max_length] for i in range(0, len(text), max_length)]
        
        print(f"文本已分为 {len(text_parts)} 部分进行处理")
        
        # 汇总音频数据
        all_audio_data = bytearray()
        
        for i, part in enumerate(text_parts):
            print(f"处理第 {i+1}/{len(text_parts)} 部分文本，长度: {len(part)}")
            
            # 对文本进行URL编码
            text_encoded = requests.utils.quote(part)
            
            # 构建GET请求参数
            params = {
                'tok': token,
                'tex': text_encoded,
                'cuid': 'picture_book_application',
                'ctp': 1,  # 客户端类型，web端
                'lan': 'zh' if language == 'zh' else 'en',
                'spd': 5,  # 语速
                'pit': 5,  # 音调
                'vol': 5,  # 音量
                'per': 4,  # 发音人，4-情感女声
                'aue': 3,  # 3-mp3格式
            }
            
            # 构建完整URL
            query_string = "&".join([f"{k}={v}" for k, v in params.items()])
            full_url = f"{short_text_url}?{query_string}"
            
            print(f"发送请求到短文本合成API")
            response = requests.get(full_url)
            
            # 检查响应
            content_type = response.headers.get('Content-Type', '')
            print(f"响应状态码: {response.status_code}, 内容类型: {content_type}")
            
            if 'audio' in content_type:
                # 成功获取音频
                print(f"成功获取音频数据，大小: {len(response.content)} 字节")
                all_audio_data.extend(response.content)
            else:
                # 请求失败
                try:
                    error_info = response.json()
                    error_msg = error_info.get('err_msg', '未知错误')
                    error_code = error_info.get('err_no', -1)
                    print(f"短文本合成失败: 错误码 {error_code}, 错误信息: {error_msg}")
                except:
                    print(f"无法解析错误响应，响应内容: {response.text[:200]}")
                # 继续处理下一段，而不是立即返回失败
        
        # 检查是否获取到任何音频数据
        if all_audio_data:
            print(f"所有音频数据合并完成，总大小: {len(all_audio_data)} 字节")
            with open(output_path, 'wb') as f:
                f.write(all_audio_data)
            print(f"音频文件已保存到: {output_path}")
            return True
        else:
            print("未获取到任何音频数据")
            return False
            
    except Exception as e:
        print(f"语音合成过程中发生异常: {str(e)}")
        import traceback
        print(f"详细错误: {traceback.format_exc()}")
        return False

@app.route('/view_image')
def view_image():
    image_path = request.args.get('path', '')
    if not image_path or not os.path.exists(image_path):
        return "图片不存在", 404
    
    # 直接使用静态文件夹方式提供图片
    directory = os.path.dirname(image_path)
    filename = os.path.basename(image_path)
    return send_from_directory(directory, filename)

@app.route('/download')
def download_file():
    file_path = request.args.get('path', '')
    if not file_path or not os.path.exists(file_path):
        return "文件不存在", 404
    
    return send_from_directory(os.path.dirname(file_path), os.path.basename(file_path), as_attachment=True)

def process_markdown_with_images(markdown_content, image_url_dict):
    """
    处理Markdown内容，保持图片和文字的交替显示
    
    参数:
        markdown_content: Markdown格式的故事内容
        image_url_dict: 图片名到URL的映射字典
    
    返回:
        处理后的HTML内容，确保图片和文字交替显示
    """
    # 分割内容为段落
    paragraphs = markdown_content.split('\n\n')
    html_parts = []
    
    # 处理标题
    title_pattern = r'^# (.+)$'
    
    # 先找出标题和角色描述
    title_index = -1
    character_description = None
    character_index = -1
    
    for i, paragraph in enumerate(paragraphs):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
            
        # 查找标题位置
        if re.match(title_pattern, paragraph, re.MULTILINE):
            title_index = i
            
        # 查找角色描述位置
        if paragraph.startswith('**角色：**'):
            character_description = paragraph
            character_index = i
            
    # 重新处理段落，调整角色描述位置
    for i, paragraph in enumerate(paragraphs):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
            
        # 处理标题
        title_match = re.match(title_pattern, paragraph, re.MULTILINE)
        if title_match:
            html_parts.append(f'<h1>{title_match.group(1)}</h1>')
            
            # 如果找到了角色描述，在标题后立即添加
            if character_description and character_index != -1 and i == title_index:
                # 转换角色描述为HTML
                para_html = character_description.replace('**角色：**', '<strong>角色：</strong>')
                para_html = para_html.replace('**词汇小课堂：**', '<strong>词汇小课堂：</strong>')
                
                # 处理角色条目
                para_html = re.sub(r'- \*\*(.*?)\*\* - (.*)', r'<div class="character"><strong>\1</strong> - \2</div>', para_html)
                
                # 处理词汇条目
                para_html = re.sub(r'- \*\*(.*?)\*\* ：(.*)', r'<div class="vocabulary"><strong>\1</strong>：\2</div>', para_html)
                para_html = re.sub(r'- \*\*(.*?)\*\*：(.*)', r'<div class="vocabulary"><strong>\1</strong>：\2</div>', para_html)
                
                html_parts.append(f'<div class="description">{para_html}</div>')
            continue
            
        # 如果这个段落就是角色描述，且已经在标题后处理过，则跳过
        if paragraph.startswith('**角色：**') and character_index != -1 and i == character_index:
            continue
            
        # 处理图片
        if paragraph.startswith('!['):
            img_pattern = r'!\[(.*?)\]\((.*?)\)'
            img_match = re.search(img_pattern, paragraph)
            if img_match:
                img_alt = img_match.group(1)
                img_path = img_match.group(2)
                img_name = os.path.basename(img_path)
                
                if img_name in image_url_dict:
                    img_path = image_url_dict[img_name]
                    # 使用view_image路由来提供图片访问，传递完整的文件路径
                    img_url = f"/view_image?path={img_path}"
                    html_parts.append(f'<div class="image-container"><img src="{img_url}" alt="{img_alt}" class="story-image"></div>')
            continue
            
        # 处理分隔线
        if paragraph == '---':
            html_parts.append('<hr>')
            continue
            
        # 处理词汇小课堂
        if paragraph.startswith('**词汇小课堂：**'):
            # 转换词汇描述为HTML
            para_html = paragraph.replace('**词汇小课堂：**', '<strong>词汇小课堂：</strong>')
            
            # 处理词汇条目
            para_html = re.sub(r'- \*\*(.*?)\*\* ：(.*)', r'<div class="vocabulary"><strong>\1</strong>：\2</div>', para_html)
            para_html = re.sub(r'- \*\*(.*?)\*\*：(.*)', r'<div class="vocabulary"><strong>\1</strong>：\2</div>', para_html)
            
            html_parts.append(f'<div class="description">{para_html}</div>')
            continue
            
        # 处理普通段落
        # 先处理强调 (bold)
        para_html = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', paragraph)
        # 再处理斜体 (italic)
        para_html = re.sub(r'\*(.*?)\*', r'<em>\1</em>', para_html)
        
        html_parts.append(f'<p class="story-paragraph">{para_html}</p>')
    
    # 将所有HTML部分合并，添加包装div以便于CSS样式处理
    final_html = '<div class="story-content">' + ''.join(html_parts) + '</div>'
    
    return final_html

if __name__ == '__main__':
    # 加载环境变量，确保应用启动时有正确的配置
    load_dotenv()
    app.run(debug=True, port=5000) 