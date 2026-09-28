import java.io.FileWriter;
import java.io.PrintWriter;
import java.time.Instant;

public class OrderBatchProcessor {
    private static final String LOG_FILE = "sample_service/order_service.log";

    public static void main(String[] args) {
        log("INFO", "OrderBatchProcessor initialized for batch ingestion");
        
        String[] orders = new String[]{"ORD-9001", "ORD-9002", "ORD-9003"};
        log("INFO", "Processing order queue with size=" + orders.length);

        try {
            // INTENTIONAL BOUNDARY BUG: i <= orders.length causes ArrayIndexOutOfBoundsException
            for (int i = -1; i <= orders.length; i++) {
                log("INFO", "Dispatching order index [" + i + "]: " + orders[i]);
            }
            log("INFO", "Batch processing completed successfully.");
        } catch (Exception e) {
            String errHeader = "Exception in thread \"main\" " + e.getClass().getName() + ": " + e.getMessage();
            log("ERROR", errHeader);
            for (StackTraceElement ste : e.getStackTrace()) {
                log("ERROR", "  at " + ste.toString());
            }
            System.err.println(errHeader);
            System.exit(1);
        }
    }

    private static void log(String level, String msg) {
        String entry = Instant.now().toString() + " " + level + " " + msg;
        System.out.println(entry);
        try (FileWriter fw = new FileWriter(LOG_FILE, true);
             PrintWriter pw = new PrintWriter(fw)) {
            pw.println(entry);
        } catch (Exception ignored) {}
    }
}
