"""Build the standalone Pipeline Links APK using the existing Android toolchain."""
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent
TOOLS=Path(r'C:\project\2.Auto gen Video\7.web app\android-app\.toolchain')
JAVA=Path(r'C:\Program Files\Eclipse Adoptium\jdk-17.0.20.8-hotspot\bin')
KEY=Path(r'C:\project\2.Auto gen Video\7.web app\android-app\debug.keystore')
ANDROID=TOOLS/'android-34/android.jar'
BUILD=ROOT/'build'/str(time.time_ns())
for name in ('gen','classes','dex'): (BUILD/name).mkdir(parents=True,exist_ok=True)
def run(args):
    result=subprocess.run([str(a) for a in args],capture_output=True,text=True,encoding='utf-8',errors='replace')
    if result.returncode:
        print(result.stdout,result.stderr)
        raise RuntimeError('Build step failed: '+str(args[0]))
run([TOOLS/'android-14/aapt2.exe','compile','--dir',ROOT/'res','-o',BUILD/'res.flata'])
run([TOOLS/'android-14/aapt2.exe','link','-I',ANDROID,'--manifest',ROOT/'AndroidManifest.xml','--java',BUILD/'gen','--auto-add-overlay','-o',BUILD/'base.apk',BUILD/'res.flata'])
sources=list((ROOT/'src').rglob('*.java'))+list((BUILD/'gen').rglob('*.java'))
run([JAVA/'javac.exe','--release','8','-encoding','UTF-8','-cp',ANDROID,'-d',BUILD/'classes',*sources])
run([JAVA/'java.exe','-cp',TOOLS/'android-14/lib/d8.jar','com.android.tools.r8.D8','--release','--lib',ANDROID,'--output',BUILD/'dex',*list((BUILD/'classes').rglob('*.class'))])
with zipfile.ZipFile(BUILD/'base.apk','a',zipfile.ZIP_DEFLATED) as apk:
    apk.write(BUILD/'dex/classes.dex','classes.dex')
run([TOOLS/'android-14/zipalign.exe','-f','4',BUILD/'base.apk',BUILD/'aligned.apk'])
out=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else ROOT/'dist/pipeline-links.apk'
out.parent.mkdir(parents=True,exist_ok=True)
run([JAVA/'java.exe','-jar',TOOLS/'android-14/lib/apksigner.jar','sign','--ks',KEY,'--ks-pass','pass:android','--key-pass','pass:android','--out',out,BUILD/'aligned.apk'])
run([JAVA/'java.exe','-jar',TOOLS/'android-14/lib/apksigner.jar','verify',out])
print('APK verified:',out, out.stat().st_size,'bytes')
