# GIGO QC

**Lacey Carbon Grid 홀 크기 자동 측정 & QC 검증 시스템**

TEM 이미지 (MRC / TIFF / PNG) 를 넣으면 그리드 홀을 자동으로 검출하고, 어떤 실험 목적에 적합한지 자동 분류해서 인포그래픽 리포트를 만들어줍니다.

---

## 🚀 가장 쉬운 방법 (Windows 설치형 - 추천)

Python 설치도 필요 없습니다. 그냥 설치 파일만 받아서 실행하세요.

1. **[GitHub Releases](https://github.com/white4477-spec/gigo-qc/releases/latest)** 페이지로 이동
2. 둘 중 하나 다운로드:
   - `GIGO-QC-Setup-x.x.x-win64.exe` ← **설치형 (추천)**: 더블클릭 → 다음→다음→완료. 바탕화면 바로가기 자동 생성
   - `GIGO-QC-Portable-x.x.x-win64.zip` ← 포터블: 압축 풀고 `GIGO-QC.exe` 더블클릭
3. 실행하면 검은 창과 브라우저가 자동으로 열립니다 (http://127.0.0.1:8765)
4. cryo-EM 이미지를 드래그&드롭으로 올리면 끝

> Windows SmartScreen 경고가 뜰 수 있습니다 (서명되지 않은 빌드라). "추가 정보" → "실행"을 누르세요.

---

## 개발자 / 직접 빌드하실 분 (소스 실행)

### 준비물: Python 3.10 이상

이미 설치되어 있다면 건너뛰세요. 확인 방법은 명령 프롬프트(`cmd`)를 열고:

```
python --version
```

`Python 3.10.x` 또는 그 이상이면 OK. 없거나 3.8 이하면 아래에서 설치:

> **Python 다운로드:** https://www.python.org/downloads/
> 설치 화면에서 **"Add Python to PATH"** 체크박스를 반드시 켜주세요. 안 켜면 GIGO QC가 Python을 찾지 못합니다.

### 1단계: 설치 (한 번만)

1. 이 폴더(`gigo-qc`)를 원하는 위치에 풀어주세요. (예: 바탕화면)
2. 폴더 안의 **`install.bat`** 파일을 더블클릭하세요.
3. 검은 창이 열리고 "필요한 라이브러리 설치 중..."이 표시됩니다. **5~10분** 정도 걸립니다.
4. "설치 완료!" 메시지가 뜨면 아무 키나 눌러 창을 닫으세요.

### 2단계: 실행 (매번)

1. **`run.bat`** 파일을 더블클릭하세요.
2. 잠시 후 브라우저가 자동으로 열리며 GIGO QC 화면이 나타납니다.
3. 분석이 끝나면 PDF/CSV 리포트를 다운로드할 수 있습니다.
4. **종료할 때**: 검은 창에서 `Ctrl + C` 를 누르거나 그냥 창을 닫으세요.

---

## macOS / Linux 사용자

터미널에서 폴더로 이동 후:

```bash
chmod +x install.sh run.sh    # 한 번만 실행 권한 부여
./install.sh                   # 설치 (한 번만)
./run.sh                       # 실행 (매번)
```

---

## 사용법

1. **이미지 업로드**: 드래그&드롭 또는 클릭해서 `.mrc`, `.tif`, `.tiff`, `.png`, `.jpg` 파일을 선택
2. **픽셀 스케일 입력**: `nm/px` 단위로 입력 (MRC 파일은 자동 감지 시도)
3. **Grid 타입**: 기본은 **자동(역방향 분류)** — 결과 분석 후 어떤 타입에 가장 적합한지 알려줍니다. 특정 타입으로 검증하려면 A/B/C 선택.
4. **분석 시작** 버튼 클릭 → 단계별 진행 상황이 실시간 표시됩니다.
5. 결과 대시보드에서:
   - KPI 카드 4종 (홀 수, 평균 직경, 원형도, 커버리지)
   - TEM 이미지 + 검출 홀 오버레이
   - 직경 분포 히스토그램, 산포도, 도넛 차트
   - 개별 홀 측정 테이블
6. **PDF 리포트 다운로드** 또는 **CSV 내보내기** 버튼으로 결과 저장

### Grid 타입 기준 (자동 분류용)

| 타입 | 홀 직경 | 원형도 | 용도 |
|---|---|---|---|
| Type A — Membrane Protein | 0.5 ~ 5.0 μm | ≥ 0.60 | 단백질 막 복합체, 소형 단백질 (<300kDa) |
| Type B — Protein Complex | 1.0 ~ 10.0 μm | ≥ 0.50 | 대형 복합체 (>300kDa), 리보솜, 바이러스 캡시드 |
| Type C — Nanomaterial / Virus | 0.2 ~ 2.0 μm | ≥ 0.55 | 나노입자, 소형 바이러스, 무기 나노소재 |
| Type D — Large Specimen | 5.0 ~ 30.0 μm | ≥ 0.40 | 세포 소기관, 대형 어셈블리, 박테리아 |

---

## 자주 겪는 문제

| 증상 | 해결 |
|---|---|
| `install.bat` 실행 시 "Python을 찾을 수 없습니다" | Python 설치 시 "Add Python to PATH" 체크를 빠뜨렸을 가능성. Python을 제거 후 재설치하면서 체크박스를 켜세요. |
| 브라우저가 자동으로 안 열림 | 직접 브라우저에서 `http://localhost:8000` 주소로 이동하세요. |
| "Address already in use" 에러 | 다른 프로그램이 8000 포트를 쓰는 중. 검은 창을 닫고 다시 시도. 그래도 안 되면 컴퓨터 재시작. |
| 분석 후 홀이 0개 검출됨 | 픽셀 스케일(nm/px)이 너무 작거나 크게 잘못 입력됐을 수 있음. 또는 이미지가 너무 어둡거나 밝아 Otsu 임계값이 부적절. 다른 샘플로 테스트해보세요. |
| 패키지 설치 중 멈춤 | 인터넷 연결 확인. 회사망/방화벽 환경이면 IT팀에 pip 외부 접속 허용 요청. |
| MRC 파일이 안 열림 | mrcfile 라이브러리 호환성 문제일 수 있음. `.mrc` 헤더가 손상되지 않았는지 ChimeraX 등에서 먼저 열어보세요. |

---

## 폴더 구조

```
gigo-qc/
├── install.bat / install.sh     ← 처음에 한 번만 실행
├── run.bat / run.sh             ← 매번 실행
├── README.md                    ← 이 파일
├── backend/                     ← FastAPI 서버 (Python)
│   ├── main.py
│   ├── analyzer.py              ← OpenCV 홀 검출 파이프라인
│   ├── classifier.py            ← Grid 타입 역방향 분류
│   ├── qc_evaluator.py          ← PASS/FAIL 판정
│   ├── report_generator.py      ← PDF 리포트
│   ├── parsers/                 ← MRC / TIFF / PNG 파일 파서
│   └── requirements.txt
└── frontend/
    └── index.html               ← 단일 HTML (Chart.js + Satoshi 폰트)
```

---

## 기술 스택

- **Backend**: Python 3.9+ · FastAPI · OpenCV · scikit-image · mrcfile · tifffile · ReportLab
- **Frontend**: HTML/CSS/JS · Chart.js · Satoshi (Fontshare) · JetBrains Mono
- **통신**: Server-Sent Events (SSE) 실시간 진행 상황 스트리밍

---

*GIGO QC v1.0 | 강원대학교 생화학과 박사과정 박윤호 | 2026*
