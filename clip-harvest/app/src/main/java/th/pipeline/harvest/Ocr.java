package th.pipeline.harvest;

import android.graphics.Bitmap;
import android.graphics.Rect;

import com.google.android.gms.tasks.Tasks;
import com.google.mlkit.vision.common.InputImage;
import com.google.mlkit.vision.text.Text;
import com.google.mlkit.vision.text.TextRecognition;
import com.google.mlkit.vision.text.TextRecognizer;
import com.google.mlkit.vision.text.latin.TextRecognizerOptions;

import java.util.ArrayList;
import java.util.List;

/**
 * อ่านตัวอักษรจากภาพด้วย ML Kit (ตัวอักษรละติน) — พอสำหรับหา "EXTRA COMM" ซึ่งเป็นภาษาอังกฤษ
 *
 * ข้อความไทยบางส่วน ML Kit ละตินอ่านไม่ได้ แต่จุดสำคัญที่ต้องอ่าน (EXTRA COMM) เป็นอังกฤษ
 * ส่วนปุ่มที่เป็นไทย/ไอคอน จะกดด้วยพิกัดที่จูนไว้แทน
 */
public class Ocr {

    public static class Word {
        public final String text;
        public final Rect box;
        Word(String text, Rect box) { this.text = text; this.box = box; }
        public int cx() { return box.centerX(); }
        public int cy() { return box.centerY(); }
    }

    private static final TextRecognizer RECOGNIZER =
            TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS);

    /** อ่านทุกบล็อกข้อความจากภาพ (รอจนเสร็จ ใช้ในเธรดพื้นหลังเท่านั้น) */
    public static List<Word> read(Bitmap bitmap) {
        List<Word> out = new ArrayList<>();
        if (bitmap == null) return out;
        try {
            Text result = Tasks.await(RECOGNIZER.process(InputImage.fromBitmap(bitmap, 0)));
            for (Text.TextBlock block : result.getTextBlocks()) {
                for (Text.Line line : block.getLines()) {
                    Rect r = line.getBoundingBox();
                    if (r != null) out.add(new Word(line.getText(), r));
                }
            }
        } catch (Throwable ignore) {
        }
        return out;
    }

    /** หา word ที่มีข้อความ (ไม่สนตัวพิมพ์เล็กใหญ่/ช่องว่าง) — คืน null ถ้าไม่เจอ */
    public static Word find(List<Word> words, String needle) {
        String n = needle.replace(" ", "").toLowerCase();
        for (Word w : words) {
            if (w.text.replace(" ", "").toLowerCase().contains(n)) return w;
        }
        return null;
    }

    public static List<Word> findAll(List<Word> words, String needle) {
        String n = needle.replace(" ", "").toLowerCase();
        List<Word> out = new ArrayList<>();
        for (Word w : words) {
            if (w.text.replace(" ", "").toLowerCase().contains(n)) out.add(w);
        }
        return out;
    }
}
