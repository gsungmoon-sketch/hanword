hanword for Linux (x86_64, glibc 2.35 or newer; systemd)
========================================================

No Python needed - the program is self-contained.

Install / upgrade (as root, from this directory):
    sudo ./install.sh                 # service on http://127.0.0.1:8088/ (this machine only)
    sudo ./install.sh --port 8090     # other port
Then open http://127.0.0.1:8088/ in a browser on this machine.

Documents are stored in /var/lib/hanword/documents (owned by the system user "hanword").
Command line (converter):  hanword convert in.docx out.hwpx    (hanword --help for all commands)

Uninstall:  sudo /opt/hanword/uninstall.sh           (keeps documents in /var/lib/hanword)
            sudo /opt/hanword/uninstall.sh --purge   (also deletes all documents)

Licences: hanword/LICENSE.txt, hanword/THIRD-PARTY-NOTICES.txt, hanword/licenses/

---------------------------------------------------------------
설치(이 폴더에서, root):  sudo ./install.sh      (다른 포트: --port 8090)
설치 후 이 PC 브라우저에서 http://127.0.0.1:8088/ 을 여세요. (이 컴퓨터에서만 접속됩니다)
문서 저장 위치: /var/lib/hanword/documents
명령줄 변환:  hanword convert 입력.docx 출력.hwpx
제거:  sudo /opt/hanword/uninstall.sh  (문서 보존, --purge 를 주면 문서까지 삭제)
