# ERD

## users

로그인 계정

| column | type | description |
|----------|----------|----------|
| id | UUID | PK |
| username | VARCHAR(50) | 로그인 ID |
| password_hash | VARCHAR(255) | bcrypt 해시 |
| role | VARCHAR(20) | ADMIN/USER |
| is_active | BOOLEAN | 사용 여부 |
| created_at | TIMESTAMP | 생성일 |
| last_login | TIMESTAMP | 마지막 로그인 |

---

## employees

직원 정보

| column | type | description |
|----------|----------|----------|
| id | UUID | PK |
| emp_no | VARCHAR(20) | 사번 |
| name | VARCHAR(100) | 이름 |
| department | VARCHAR(100) | 부서 |
| position | VARCHAR(100) | 직위 |
| rank | VARCHAR(100) | 직급 |
| email | VARCHAR(255) | 이메일 |
| phone | VARCHAR(50) | 연락처 |
| hire_date | DATE | 입사일 |
| status | VARCHAR(20) | ACTIVE/INACTIVE |
| created_at | TIMESTAMP | 생성일 |

---

## assets

자산 정보

| column | type | description |
|----------|----------|----------|
| id | UUID | PK |
| asset_no | VARCHAR(50) | 자산번호 |
| asset_type | VARCHAR(30) | LAPTOP/DESKTOP/MONITOR/SERVER/OTHER |
| manufacturer | VARCHAR(100) | 제조사 |
| model | VARCHAR(255) | 모델명 |
| serial_no | VARCHAR(255) | 시리얼번호 |
| cpu | VARCHAR(255) | CPU |
| memory_gb | INTEGER | 메모리 |
| os | VARCHAR(100) | 운영체제 |
| purchase_type | VARCHAR(20) | PURCHASE/RENTAL |
| purchase_date | DATE | 구매일 |
| purchase_price | NUMERIC(12,2) | 구매금액 |
| rental_end_date | DATE | 렌탈만료일 |
| qr_code | VARCHAR(255) | QR 코드값 |
| status | VARCHAR(20) | IN_USE/STORAGE/REPAIR/DISPOSED |
| notes | TEXT | 비고 |
| created_at | TIMESTAMP | 생성일 |

---

## asset_assignments

현재 사용자 할당 정보

| column | type | description |
|----------|----------|----------|
| id | UUID | PK |
| asset_id | UUID | assets FK |
| employee_id | UUID | employees FK |
| assigned_at | TIMESTAMP | 할당일 |
| returned_at | TIMESTAMP | 반납일 |

---

## asset_history

자산 이력

| column | type | description |
|----------|----------|----------|
| id | UUID | PK |
| asset_id | UUID | assets FK |
| action_type | VARCHAR(50) | ASSIGN/RETURN/REPAIR/IP_CHANGE |
| description | TEXT | 상세내용 |
| created_by | UUID | users FK |
| created_at | TIMESTAMP | 생성일 |

---

## ip_ranges

IP 대역 관리

| column | type | description |
|----------|----------|----------|
| id | UUID | PK |
| name | VARCHAR(100) | 3층 임직원망 |
| start_ip | VARCHAR(50) | 시작 IP |
| end_ip | VARCHAR(50) | 종료 IP |
| vlan | VARCHAR(50) | VLAN |
| gateway | VARCHAR(50) | 게이트웨이 |
| dns | VARCHAR(50) | DNS |
| description | TEXT | 비고 |

---

## ip_assignments

IP 할당

| column | type | description |
|----------|----------|----------|
| id | UUID | PK |
| asset_id | UUID | assets FK |
| ip_range_id | UUID | ip_ranges FK |
| ip_address | VARCHAR(50) | 할당 IP |
| status | VARCHAR(20) | USED/FREE/RESERVED |
| assigned_at | TIMESTAMP | 할당일 |

---

## rental_contracts

렌탈 계약

| column | type | description |
|----------|----------|----------|
| id | UUID | PK |
| asset_id | UUID | assets FK |
| vendor | VARCHAR(100) | 한빛렌탈 |
| contract_no | VARCHAR(100) | 계약번호 |
| start_date | DATE | 시작일 |
| end_date | DATE | 종료일 |
| monthly_fee | NUMERIC(12,2) | 월 렌탈료 |
| status | VARCHAR(20) | ACTIVE/ENDED |

---

## software_products

소프트웨어

| column | type | description |
|----------|----------|----------|
| id | UUID | PK |
| name | VARCHAR(255) | 제품명 |
| vendor | VARCHAR(255) | 제조사 |
| license_type | VARCHAR(50) | USER/DEVICE |
| expire_date | DATE | 만료일 |

---

## software_installations

설치 현황

| column | type | description |
|----------|----------|----------|
| id | UUID | PK |
| software_id | UUID | software_products FK |
| asset_id | UUID | assets FK |
| installed_at | DATE | 설치일 |

---

## license_pools

라이선스 관리

| column | type | description |
|----------|----------|----------|
| id | UUID | PK |
| software_id | UUID | software_products FK |
| purchased_count | INTEGER | 구매 수량 |
| used_count | INTEGER | 사용 수량 |
| expire_date | DATE | 만료일 |