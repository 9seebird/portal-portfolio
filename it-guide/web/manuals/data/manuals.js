// 온빛 IT 매뉴얼 포털 - 내용 파일
// 포털의 "편집 모드"에서 수정 후 저장하면 이 파일이 새로 만들어집니다.
// 직접 편집해도 됩니다. (이미지 경로는 images/ 폴더 기준)
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
    },
    {
      "id": "sample-erp",
      "icon": "샘",
      "title": "샘플 ERP 접속 매뉴얼",
      "subtitle": "",
      "contactNote": "궁금한 점은 IT 담당자에게 문의해 주세요.",
      "sections": [
        {
          "title": "1. 프로그램 설치",
          "blocks": [
            {
              "steps": [
                "사내 자료실에서 설치 파일을 내려받습니다.",
                "내려받은 파일을 오른쪽 버튼으로 눌러 [관리자 권한으로 실행] 을 고릅니다.",
                "설치 경로는 바꾸지 말고 [다음] 을 눌러 진행합니다."
              ],
              "images": [
                "sample-erp/02_1.png"
              ]
            },
            {
              "steps": [
                "설치가 끝나면 바탕화면에 아이콘이 생깁니다.",
                "처음 실행하면 보안 경고가 뜨는데 [허용] 을 누릅니다."
              ],
              "images": [
                "sample-erp/03_1.png"
              ]
            }
          ]
        },
        {
          "title": "2. 접속 정보 입력",
          "blocks": [
            {
              "steps": [
                "아이디는 사번, 비밀번호는 처음에 받은 임시 비밀번호를 넣습니다.",
                "접속 서버는 목록에서 [운영] 을 고릅니다.",
                "처음 접속하면 비밀번호를 바꾸라는 창이 뜹니다."
              ],
              "images": [
                "sample-erp/04_1.png"
              ]
            }
          ]
        },
        {
          "title": "3. 안 될 때 확인할 것",
          "blocks": [
            {
              "steps": [
                "증상 · 원인 · 해결",
                "접속 창이 안 뜸 · 프로그램이 덜 설치됨 · 지우고 다시 설치",
                "비밀번호가 틀리다고 나옴 · 임시 비밀번호 기간 지남 · 담당자에게 재발급 요청",
                "접속은 되는데 화면이 비어 있음 · 권한이 아직 없음 · 담당자에게 권한 신청"
              ],
              "images": []
            }
          ]
        }
      ]
    },
    {
      "id": "sample-groupware",
      "icon": "샘",
      "title": "샘플 그룹웨어 사용 매뉴얼",
      "subtitle": "",
      "contactNote": "그룹웨어 관련 문의는 IT 담당자에게 주세요.",
      "sections": [
        {
          "title": "1. 로그인",
          "blocks": [
            {
              "steps": [
                "주소창에 사내 그룹웨어 주소를 넣습니다.",
                "아이디는 사번, 비밀번호는 메일 비밀번호와 같습니다.",
                "[로그인 유지] 는 공용 PC 에서는 켜지 마세요."
              ],
              "images": [
                "sample-groupware/02_1.png"
              ]
            }
          ]
        },
        {
          "title": "2. 결재 올리기",
          "blocks": [
            {
              "steps": [
                "왼쪽 [결재함] 을 누릅니다.",
                "[새 결재] 를 누르고 양식을 고릅니다.",
                "결재선은 팀장 → 본부장 순으로 넣습니다.",
                "첨부는 20MB 까지 됩니다."
              ],
              "images": [
                "sample-groupware/03_1.png"
              ]
            }
          ]
        },
        {
          "title": "3. 자주 쓰는 기능",
          "blocks": [
            {
              "steps": [
                "게시판 글은 [즐겨찾기] 로 모아 둘 수 있습니다.",
                "일정은 팀 달력과 자동으로 맞춰집니다."
              ],
              "images": [
                "sample-groupware/04_1.png"
              ]
            }
          ]
        }
      ]
    }
  ]
};
