# API Specification

## Auth

### POST /auth/login

로그인

### Request

```json
{
  "username": "admin",
  "password": "password"
}
```

### Response

```json
{
  "access_token": "jwt_token",
  "token_type": "bearer"
}
```

---

### GET /auth/me

내 정보 조회

---

## Users

### GET /users

사용자 목록 조회

### GET /users/{id}

사용자 상세 조회

### POST /users

사용자 생성

### PUT /users/{id}

사용자 수정

### DELETE /users/{id}

사용자 삭제

---

## Employees

### GET /employees

직원 목록 조회

#### Query

- name
- department
- status

### GET /employees/{id}

직원 상세 조회

### POST /employees

직원 등록

### PUT /employees/{id}

직원 수정

### DELETE /employees/{id}

직원 비활성화

---

## Assets

### GET /assets

자산 목록 조회

#### Query

- asset_type
- status
- employee_id

### GET /assets/{id}

자산 상세 조회

### POST /assets

자산 등록

### PUT /assets/{id}

자산 수정

### DELETE /assets/{id}

자산 삭제

### GET /assets/{id}/history

자산 이력 조회

### GET /assets/{id}/qr

QR 코드 조회

---

## Asset Assignments

### POST /asset-assignments

자산 할당

### POST /asset-assignments/return

자산 회수

### GET /asset-assignments

할당 현황 조회

---

## IP Management

### GET /ip-ranges

IP 대역 조회

### POST /ip-ranges

IP 대역 등록

### GET /ip-assignments

IP 할당 조회

### POST /ip-assignments

IP 할당

### DELETE /ip-assignments/{id}

IP 회수

---

## Rental Contracts

### GET /rental-contracts

렌탈 계약 조회

### POST /rental-contracts

렌탈 계약 등록

### PUT /rental-contracts/{id}

렌탈 계약 수정

### GET /rental-contracts/expiring

만료 예정 조회

---

## Software Products

### GET /software-products

소프트웨어 목록

### POST /software-products

소프트웨어 등록

### PUT /software-products/{id}

소프트웨어 수정

---

## Software Installations

### GET /software-installations

설치 현황 조회

### POST /software-installations

설치 등록

### DELETE /software-installations/{id}

설치 제거

---

## License Pools

### GET /license-pools

라이선스 조회

### POST /license-pools

라이선스 등록

### PUT /license-pools/{id}

라이선스 수정

### GET /license-pools/expiring

만료 예정 라이선스 조회

---

## Dashboard

### GET /dashboard/summary

요약 정보

### Response

```json
{
  "total_assets": 120,
  "assigned_assets": 100,
  "rental_expiring": 5,
  "license_expiring": 3,
  "ip_usage_rate": 78
}
```

---

## Import

### POST /import/employees

직원 CSV 업로드

### POST /import/assets

자산 CSV 업로드

### POST /import/licenses

라이선스 CSV 업로드

---

## Export

### GET /export/employees

직원 엑셀 다운로드

### GET /export/assets

자산 엑셀 다운로드

### GET /export/licenses

라이선스 엑셀 다운로드

### GET /export/ip

IP 현황 엑셀 다운로드

### GET /export/rentals

렌탈 현황 엑셀 다운로드