"""Build RosettaScreen.apk without Gradle, using the Android SDK + OpenJDK that ship inside Unity.

    python build_apk.py [--unity "C:\\Program Files\\Unity\\Hub\\Editor\\2022.3.22f1"]
"""
import argparse, glob, os, shutil, subprocess, sys, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument('--unity', default=r'C:\Program Files\Unity\Hub\Editor\2022.3.22f1')
a = ap.parse_args()
AP = os.path.join(a.unity, r'Editor\Data\PlaybackEngines\AndroidPlayer')
JDK = os.path.join(AP, 'OpenJDK')
BT = sorted(glob.glob(os.path.join(AP, 'SDK', 'build-tools', '*')))[-1]
JAR = sorted(glob.glob(os.path.join(AP, 'SDK', 'platforms', 'android-*', 'android.jar')))[-1]
OUT = os.path.join(HERE, 'build')
env = dict(os.environ, JAVA_HOME=JDK, PATH=os.path.join(JDK, 'bin') + os.pathsep + os.environ['PATH'])


def run(*cmd):
    print('>', os.path.basename(cmd[0]), *[os.path.basename(c) if os.path.isabs(c) else c for c in cmd[1:6]], flush=True)
    subprocess.run(list(cmd), check=True, env=env)


shutil.rmtree(OUT, ignore_errors=True)
os.makedirs(os.path.join(OUT, 'classes'))
srcs = glob.glob(os.path.join(HERE, 'src', '**', '*.java'), recursive=True)
run(os.path.join(JDK, 'bin', 'javac.exe'), '-source', '1.8', '-target', '1.8', '-Xlint:-options', '-encoding', 'utf-8',
    '-cp', JAR, '-d', os.path.join(OUT, 'classes'), *srcs)
classes = glob.glob(os.path.join(OUT, 'classes', '**', '*.class'), recursive=True)
run(os.path.join(JDK, 'bin', 'java.exe'), '-cp', os.path.join(BT, 'lib', 'd8.jar'), 'com.android.tools.r8.D8',   # d8.bat needs Java 8
    '--min-api', '16', '--lib', JAR, '--output', OUT, *classes)
run(os.path.join(BT, 'aapt2.exe'), 'link', '-o', os.path.join(OUT, 'unsigned.apk'), '-I', JAR,
    '--manifest', os.path.join(HERE, 'AndroidManifest.xml'), '--min-sdk-version', '16', '--target-sdk-version', '17')
with zipfile.ZipFile(os.path.join(OUT, 'unsigned.apk'), 'a', zipfile.ZIP_DEFLATED) as z:
    z.write(os.path.join(OUT, 'classes.dex'), 'classes.dex')
run(os.path.join(BT, 'zipalign.exe'), '-f', '-p', '4', os.path.join(OUT, 'unsigned.apk'), os.path.join(OUT, 'aligned.apk'))
ks = os.path.join(HERE, 'debug.keystore')                     # a local throwaway signing key (not a secret)
if not os.path.exists(ks):
    run(os.path.join(JDK, 'bin', 'keytool.exe'), '-genkeypair', '-keystore', ks, '-storepass', 'android', '-keypass', 'android',
        '-alias', 'rosetta', '-keyalg', 'RSA', '-keysize', '2048', '-validity', '10000', '-dname', 'CN=Rosetta Screen')
apk = os.path.join(HERE, 'RosettaScreen.apk')
run(os.path.join(JDK, 'bin', 'java.exe'), '-jar', os.path.join(BT, 'lib', 'apksigner.jar'), 'sign', '--ks', ks, '--ks-pass', 'pass:android', '--key-pass', 'pass:android',
    '--min-sdk-version', '16', '--out', apk, os.path.join(OUT, 'aligned.apk'))
print('built', apk, os.path.getsize(apk), 'bytes')
