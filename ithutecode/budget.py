"""Integer microcurrency accounting; trusted pricing and usage supplied by caller."""
class BudgetLedger:
    def __init__(self, queue):
        self.queue = queue
        with queue.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS project_budgets (
                project_id TEXT PRIMARY KEY, limit_units INTEGER NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS ai_reservations (
                job_id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                reserved INTEGER NOT NULL, actual INTEGER
            )""")

    @staticmethod
    def _amount(value):
        if type(value) is not int or not 0 <= value <= 10**12:
            raise ValueError("Invalid budget amount")
        return value

    def configure(self, project_id, limit_units):
        self._amount(limit_units)
        with self.queue.transaction() as db:
            db.execute("""INSERT INTO project_budgets VALUES (?,?)
                ON CONFLICT(project_id) DO UPDATE SET limit_units=excluded.limit_units""",
                (project_id, limit_units))

    def reserve(self, claimed, amount):
        self._amount(amount)
        if not amount:
            raise ValueError("Positive reservation required")
        with self.queue.transaction() as db:
            row = db.execute("""SELECT project_id FROM coding_jobs WHERE id=? AND lease=?
                AND status='running' AND expires>?""",
                (claimed["id"], claimed["lease"], self.queue.clock())).fetchone()
            project = claimed["project_id"]
            if row is None or row["project_id"] != project:
                raise PermissionError("Budget lease mismatch")
            if db.execute("SELECT 1 FROM ai_reservations WHERE job_id=?", (claimed["id"],)).fetchone():
                raise RuntimeError("AI request already reserved; reconcile before retry")
            limit = db.execute("SELECT limit_units FROM project_budgets WHERE project_id=?", (project,)).fetchone()
            used = db.execute("""SELECT COALESCE(SUM(COALESCE(actual,reserved)),0)
                FROM ai_reservations WHERE project_id=?""", (project,)).fetchone()[0]
            if limit is None or used + amount > limit[0]:
                raise PermissionError("Project budget exhausted or not configured")
            db.execute("INSERT INTO ai_reservations VALUES (?,?,?,NULL)", (claimed["id"], project, amount))

    def settle(self, job_id, actual):
        """Trusted accounting only; actual usage must be independently verified.
        Overruns remain recorded and block further reservations as appropriate.
        """
        self._amount(actual)
        with self.queue.transaction() as db:
            row = db.execute("SELECT actual FROM ai_reservations WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            if row["actual"] is not None and row["actual"] != actual:
                raise ValueError("Settlement already recorded")
            db.execute("UPDATE ai_reservations SET actual=? WHERE job_id=?", (actual,job_id))

    def balance(self, project_id):
        with self.queue.transaction() as db:
            limit = db.execute("SELECT limit_units FROM project_budgets WHERE project_id=?", (project_id,)).fetchone()
            if limit is None:
                raise KeyError(project_id)
            used = db.execute("""SELECT COALESCE(SUM(COALESCE(actual,reserved)),0)
                FROM ai_reservations WHERE project_id=?""", (project_id,)).fetchone()[0]
            return {"limit":limit[0],"committed":used,"remaining":limit[0]-used}
