# 기준 음성

소유권 또는 명시적인 사용 권한이 확인된 음성만 추가합니다.

현재 서비스 프리셋:

- `man_happy.wav`: 남성 · 기쁨
- `man_serious.wav`: 남성 · 진지함
- `woman_happy.wav`: 여성 · 기쁨
- `woman_serious.wav`: 여성 · 진지함
- `woman_whisper.wav`: 여성 · 속삭임

현재 5개 기준 음성은 팀에서 사용 권한과 용량을 확인한 뒤 Git으로 추적합니다.
새 음성을 추가할 때도 권리 관계와 저장소 용량을 먼저 확인해야 합니다.

배경음과 잔향이 적고 발음이 선명한 모노 WAV를 사용합니다. `man_whisper.wav`와
`man_whisper2.wav`는 결과가 불안정해 서비스에서 제외되며 Git에서도 추적하지
않습니다.
