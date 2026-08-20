# 실제 라우팅. 80 과 8082 가 **똑같이** 쓴다.
# 여기 한 곳만 고치면 두 입구에 같이 반영된다 — 갈라 두면 언젠가 어긋난다.
# ── 챗 포털 (메인) ───────────────────────────────────────
    location / {
        set $portal_upstream http://demo-portal:8080;
        proxy_pass $portal_upstream;

        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        # 클라이언트가 직접 넣은 X-Forwarded-For 를 덮어쓴다.
        # 그대로 두면 접속 IP 를 위조할 수 있고, 포털의 IP 제한이 무의미해진다.
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 어느 입구로 들어왔는가. 80 이면 0, 8082(주인 전용)면 1.
        # 부르는 server 블록이 set $demo_admin 으로 정한다.
        # 클라이언트가 같은 이름의 헤더를 넣어도 여기서 덮어써진다.
        proxy_set_header X-Demo-Admin      $demo_admin;

        # 챗 응답은 SSE(text/event-stream) 로 조금씩 내려온다.
        # 버퍼링을 켜 두면 다 끝난 뒤 한 번에 나와서 진행 표시가 무의미해진다.
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
        chunked_transfer_encoding on;

        # 화면(HTML/JS)을 캐시하면 배포해도 직원 브라우저에는 옛 화면이 남는다.
        add_header Cache-Control "no-store, must-revalidate" always;
    }

    # =================================================================
    # 앱별 설정을 여기서 끌어온다.
    #
    #   proxy/apps/ai-report.conf      ← 앱 하나에 파일 하나
    #   proxy/apps/meeting-room.conf
    #
    # 앱을 추가할 때 이 파일은 건드리지 않는다. apps/ 에 파일만 새로 넣는다.
    #   .\new-app.ps1 meeting-room
    #
    # 파일이 하나도 없어도 nginx 는 정상적으로 뜬다 (와일드카드 include).
    # =================================================================
    include /etc/nginx/apps/*.conf;

    # 권한이 없을 때 나가는 화면. 앱마다 따로 만들지 않아도 된다.
    error_page 401 = @login;
    error_page 403 = @denied;

    location @login {
        return 302 /login;
    }
    location @denied {
        default_type text/html;
        return 403 '<!doctype html><html lang="ko"><meta charset="utf-8"><title>접근 권한 없음</title><body style="margin:0;display:grid;place-items:center;height:100vh;font-family:system-ui,sans-serif;background:#f5f6f8;color:#1f2023"><div style="text-align:center"><div style="font-size:17px;font-weight:650;margin-bottom:8px">이 서비스를 이용할 권한이 없습니다</div><div style="font-size:13px;color:#8a8e97;margin-bottom:20px">필요하시면 IT 담당자에게 문의해주세요.</div><a href="/" style="display:inline-block;padding:9px 18px;border-radius:9px;background:#132033;color:#fff;text-decoration:none;font-size:13.5px">포탈로 돌아가기</a></div></body></html>';
    }
