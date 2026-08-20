/* 이 파일은 자동으로 만들어졌습니다. 화면의 [편집 모드]에서 고친 뒤
   [저장]으로 다시 받으면 이 파일을 덮어쓰면 됩니다.

   원본은 사내에서 쓰던 PPT 매뉴얼입니다. 포트폴리오에 넣으면서
   캡처 속 사내 정보(관리서버 IP·관리자 계정·PC 목록의 IP·호스트명·
   사업장 이름·제품 시리얼)는 가상 회사 값으로 바꾸거나 가렸습니다. */
window.MANUAL_DATA = {
  "site": {
    "title": "온빛 IT 매뉴얼",
    "subtitle": "사내 프로그램 설치·사용 안내. 궁금한 건 인사총무팀 IT 담당자에게 문의하세요.",
    "imageSize": "m"
  },
  "manuals": [
    {
      "id": "hancom-office",
      "icon": "한",
      "title": "한컴오피스 2024 설치",
      "subtitle": "기존 사용자는 구 버전 한글을 삭제한 뒤 설치하세요.",
      "contactNote": "문의: 인사총무팀 IT 담당자",
      "sections": [
        {
          "title": "1. 기존에 설치된 한글 삭제하기",
          "blocks": [
            {
              "steps": [
                "한글 구 버전을 삭제합니다.",
                "제어판 > 프로그램 추가/제거 > 한글과컴퓨터 옛 버전을 고른 뒤 [제거]를 누릅니다."
              ],
              "images": [
                "hancom/01-remove-old.png"
              ]
            }
          ]
        },
        {
          "title": "2. 한컴오피스 설치하기",
          "blocks": [
            {
              "steps": [
                "‘Install.exe’를 더블 클릭해 실행합니다.",
                "[확인]을 눌러 프로그램 설치를 시작합니다."
              ],
              "images": [
                "hancom/02-install-start.png"
              ]
            },
            {
              "steps": [
                "[동의함]에 체크합니다.",
                "[다음] 버튼을 누릅니다."
              ],
              "images": [
                "hancom/03-agree.png"
              ]
            },
            {
              "steps": [
                "시리얼 넘버를 입력한 뒤 [다음]을 누릅니다.",
                "시리얼 넘버는 IT 담당자에게 문의하세요."
              ],
              "images": [
                "hancom/04-serial.png"
              ]
            },
            {
              "steps": [
                "설치가 끝나면 [마침] 버튼을 누릅니다."
              ],
              "images": [
                "hancom/05-finish.png"
              ]
            },
            {
              "steps": [
                "설치 후 재부팅을 권장합니다."
              ],
              "images": [
                "hancom/06-reboot.png"
              ]
            }
          ]
        }
      ]
    },
    {
      "id": "kaspersky-ksc",
      "icon": "K",
      "title": "카스퍼스키 중앙 관리 툴",
      "subtitle": "중앙 관리 콘솔(KSC) 설치와 사용. IT 매니저 전용입니다.",
      "contactNote": "문의: 인사총무팀 IT 담당자",
      "sections": [
        {
          "title": "1. Kaspersky Security Center 다운로드",
          "blocks": [
            {
              "steps": [
                "https://www.kaspersky.com/small-to-medium-business-security/downloads/endpoint 에 접속합니다.",
                "Kaspersky Security Center 15.1.0.22239 버전을 내려받습니다. (서버 버전과 맞춰야 합니다)"
              ],
              "images": [
                "kaspersky/01-download-1.png",
                "kaspersky/01-download-2.png"
              ]
            }
          ]
        },
        {
          "title": "2. Kaspersky Security Center 설치하기",
          "blocks": [
            {
              "steps": [
                "내려받은 설치 파일을 더블 클릭합니다.",
                "[설치] 버튼을 누릅니다. — 실제 설치가 아니라 압축 해제입니다."
              ],
              "images": [
                "kaspersky/02-extract-1.png",
                "kaspersky/02-extract-2.png"
              ]
            },
            {
              "steps": [
                "압축 해제가 끝나면 C:\\ksc 15.1\\ko 폴더로 이동합니다.",
                "setup.exe 를 실행합니다."
              ],
              "images": [
                "kaspersky/03-setup-1.png",
                "kaspersky/03-setup-2.png"
              ]
            },
            {
              "steps": [
                "설치 마법사가 뜨면 안내대로 [다음]을 눌러 진행합니다."
              ],
              "images": [
                "kaspersky/04-wizard-1.png",
                "kaspersky/04-wizard-2.png"
              ]
            },
            {
              "steps": [
                "대상 폴더와 설치 준비 화면을 확인하고 [설치]를 누릅니다."
              ],
              "images": [
                "kaspersky/05-wizard-1.png",
                "kaspersky/05-wizard-2.png"
              ]
            },
            {
              "steps": [
                "설치가 끝나면 [마침] 버튼을 누릅니다."
              ],
              "images": [
                "kaspersky/06-done-1.png",
                "kaspersky/06-done-2.png"
              ]
            }
          ]
        },
        {
          "title": "3. Kaspersky Security Center 설정하기",
          "blocks": [
            {
              "steps": [
                "관리 콘솔을 실행하면 연결 설정 창이 뜹니다. 계정 정보를 입력합니다.",
                "중앙 관리 서버에 연결하여 인증서를 내려받는 항목이 선택된 상태로 [확인]을 누릅니다."
              ],
              "images": [
                "kaspersky/07-connect-1.png",
                "kaspersky/07-connect-2.png"
              ]
            },
            {
              "steps": [
                "인증서가 발급됐다는 창이 뜨면 [예]를 누릅니다.",
                "관리 콘솔 창이 열리면 설정 완료입니다."
              ],
              "images": [
                "kaspersky/08-cert-1.png",
                "kaspersky/08-cert-2.png"
              ]
            },
            {
              "steps": [
                "왼쪽 메뉴에서 [관리 중인 기기]를 고르면 층별로 사용 중인 컴퓨터를 확인할 수 있습니다.",
                "층별·공장별로 그룹이 나뉘어 있고, 정책과 작업 메뉴도 여기서 볼 수 있습니다."
              ],
              "images": [
                "kaspersky/09-console.png"
              ]
            }
          ]
        }
      ]
    }
  ]
};
