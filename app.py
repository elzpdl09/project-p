import os
from flask import Flask, jsonify, request
from flask_cors import CORS  # 이 부분이 반드시 있어야 합니다.
from dotenv import load_dotenv
from supabase import create_client, Client
import json
import uuid

load_dotenv()
# ↓↓↓ [체크!] 이 줄이 반드시 signup 함수보다 위에 있어야 합니다 ↓↓↓
url: str = os.getenv("SUPABASE_URL")
key: str = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(url, key)

app = Flask(__name__)

# [중요] 모든 도메인에서 오는 요청을 허용하도록 설정
CORS(app, resources={r"/api/*": {"origins": "*"}})

# app.py 의 일부
@app.route('/api/test-connection', methods=['GET'])
def test_connection():
    return jsonify({
        "status": "connected",
        "message": "백엔드 서버와 성공적으로 연결되었습니다!"
    })

@app.route('/api/signup', methods=['POST'])
def signup():
    data = request.json
    user_id = data.get('user_id')
    password = data.get('password')
    nickname = data.get('nickname')

    try:
        # 1. 먼저 해당 아이디가 이미 존재하는지 확인합니다.
        existing_user = supabase.table("custom_users")\
            .select("user_id")\
            .eq("user_id", user_id)\
            .execute()

        if len(existing_user.data) > 0:
            return jsonify({"status": "error", "message": "이미 존재하는 아이디입니다."}), 409

        # 2. 존재하지 않는다면 데이터 삽입을 진행합니다.
        result = supabase.table("custom_users").insert({
            "user_id": user_id,
            "password": password,
            "nickname": nickname
        }).execute()
        
        return jsonify({"status": "success", "message": "회원가입 완료"}), 201
        
    except Exception as e:
        return jsonify({"status": "error", "message": "서버 오류가 발생했습니다."}), 500
    
@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    user_id = data.get('user_id')
    password = data.get('password')

    try:
        # 로그인 성공 시 닉네임과 함께 사용자의 고유 id(UUID)를 가져옵니다.
        result = supabase.table("custom_users")\
            .select("id, nickname")\
            .eq("user_id", user_id)\
            .eq("password", password)\
            .execute()

        if len(result.data) > 0:
            user = result.data[0]
            return jsonify({
                "status": "success", 
                "nickname": user['nickname'],
                "user_uuid": user['id']  # ← 이 UUID가 게시글 작성 시 필요합니다.
            }), 200
        else:
            return jsonify({"status": "error", "message": "아이디 또는 비밀번호가 틀렸습니다."}), 401
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    
@app.route('/api/posts', methods=['POST'])
def create_post():
    # 입력값 가져오기
    title = request.form.get('title')
    content = request.form.get('content')
    link = request.form.get('link')
    source = request.form.get('source')
    user_uuid = request.form.get('user_uuid')
    author_nickname = request.form.get('author_nickname', '익명')
    tags_raw = request.form.get('tags')
    
    # 1. 이미지 파일 받기
    image_file = request.files.get('image')

    try:
        tags = json.loads(tags_raw) if tags_raw else []
        image_url = ""

        # 이미지가 있고 파일명이 존재할 때만 실행
        if image_file and image_file.filename != '':
            import os
            # 확장자 추출 및 파일명 생성
            file_ext = os.path.splitext(image_file.filename)[1].lower()
            file_name = f"{uuid.uuid4()}{file_ext}"
            
            # [중요] 파일 데이터 읽기 전 포인터 초기화
            image_file.seek(0)
            file_data = image_file.read()
            
            # [중요] 파일 타입 설정 (브라우저 출력용)
            content_type = image_file.content_type or "image/jpeg"
            
            # 2. Supabase Storage 업로드 (버킷명: archive-media 확인)
            upload_res = supabase.storage.from_("archive-media").upload(
                path=file_name,
                file=file_data,
                file_options={"content-type": content_type, "x-upsert": "true"}
            )
            
            # 3. 공개 URL 생성 및 정확한 문자열 추출
            # .get_public_url()은 주소 문자열만 주거나, 객체를 줄 수 있음
            url_res = supabase.storage.from_("archive-media").get_public_url(file_name)
            
            # 라이브러리 버전에 따라 결과 처리 (문자열 혹은 객체)
            if isinstance(url_res, str):
                image_url = url_res
            elif hasattr(url_res, 'public_url'):
                image_url = url_res.public_url
            else:
                # url_res가 dict 형태일 경우 대비
                image_url = url_res.get('publicURL', str(url_res))

        # 4. DB 저장 (image_url 변수가 확실히 채워졌는지 확인)
        insert_data = {
            "title": title,
            "content": content,
            "image_url": image_url, 
            "author_nickname": author_nickname,
            "source": source,
            "author_uuid": user_uuid if (user_uuid and user_uuid != "null") else None,
            "tags": tags,
            "media_type": "image"
        }
        
        # 실제 DB Insert 실행
        supabase.table("posts").insert(insert_data).execute()
        
        return jsonify({"status": "success", "message": "등록 완료"}), 201
        
    except Exception as e:
        # 터미널(로그)에 에러 원인 출력
        print(f"❌ 게시글 등록 에러 발생: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500
# 게시물 목록 불러오기 (메인 화면용)
@app.route('/api/posts', methods=['GET'])
def get_posts():
    try:
        # posts 테이블에서 모든 데이터를 가져옵니다. 
        # 생성일(created_at) 기준 내림차순 정렬하여 최신순으로 가져오기
        response = supabase.table("posts")\
            .select("*")\
            .order("created_at", desc=True)\
            .execute()
            
        return jsonify(response.data), 200
    except Exception as e:
        print(f"Error fetching posts: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/posts/<int:post_id>/comments', methods=['GET'])
def get_comments(post_id):
    try:
        # 해당 post_id를 가진 댓글들을 최신순으로 가져오기
        response = supabase.table("comments") \
            .select("*") \
            .eq("post_id", post_id) \
            .order("created_at", desc=False) \
            .execute()
            
        return jsonify(response.data), 200
    except Exception as e:
        print(f"댓글 로드 에러: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# [추가] 댓글 등록하기
@app.route('/api/posts/<int:post_id>/comments', methods=['POST'])
def add_comment(post_id):
    data = request.json
    content = data.get('content')
    # 로그인 기능을 사용 중이라면 현재 사용자의 닉네임을 가져올 수 있습니다.
    nickname = data.get('author_nickname', '익명')

    if not content:
        return jsonify({"status": "error", "message": "내용을 입력해주세요."}), 400

    try:
        # SQL 설계에 맞게 데이터 삽입
        result = supabase.table("comments").insert({
            "post_id": post_id,
            "content": content,
            "author_nickname": nickname
        }).execute()
        
        return jsonify({"status": "success", "message": "댓글이 등록되었습니다."}), 201
    except Exception as e:
        print(f"댓글 저장 에러: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/posts/<int:post_id>/like', methods=['POST'])
def toggle_like(post_id):
    data = request.json
    user_uuid = data.get('user_uuid')
    if not user_uuid:
        return jsonify({"status": "error", "message": "로그인이 필요합니다."}), 401

    try:
        # 1. 이미 좋아요를 눌렀는지 확인
        existing_like = supabase.table("likes")\
            .select("*")\
            .eq("post_id", post_id)\
            .eq("user_uuid", user_uuid)\
            .execute()

        if existing_like.data:
            # 2. 이미 있다면 삭제 (취소) -> 트리거에 의해 posts.like_count 자동 -1
            supabase.table("likes")\
                .delete()\
                .eq("post_id", post_id)\
                .eq("user_uuid", user_uuid)\
                .execute()
            status = "unliked"
        else:
            # 3. 없다면 삽입 (좋아요) -> 트리거에 의해 posts.like_count 자동 +1
            supabase.table("likes").insert({
                "post_id": post_id,
                "user_uuid": user_uuid
            }).execute()
            status = "liked"

        # 4. 최신 좋아요 수 가져오기
        post_res = supabase.table("posts").select("like_count").eq("id", post_id).single().execute()
        
        return jsonify({
            "status": "success", 
            "like_status": status,
            "like_count": post_res.data['like_count']
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
@app.route('/api/posts/<int:post_id>', methods=['DELETE'])
def delete_post(post_id):
    # 요청 보낸 사람의 UUID 확인
    data = request.json
    user_uuid = data.get('user_uuid')

    if not user_uuid:
        return jsonify({"status": "error", "message": "권한이 없습니다."}), 401

    try:
        # 1. 먼저 게시글의 작성자가 맞는지 확인
        post = supabase.table("posts").select("author_uuid").eq("id", post_id).single().execute()
        
        if not post.data or post.data['author_uuid'] != user_uuid:
            return jsonify({"status": "error", "message": "삭제 권한이 없습니다."}), 403

        # 2. 본인 확인 완료 시 삭제 수행
        supabase.table("posts").delete().eq("id", post_id).execute()
        
        return jsonify({"status": "success", "message": "게시물이 삭제되었습니다."}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    
if __name__ == '__main__':
    # 로컬에서 실행 시 반드시 5000번 포트인지 확인
    app.run(debug=True, port=5000)