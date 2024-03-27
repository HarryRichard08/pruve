from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel
from typing import List, Optional, Union
import jwt
import psycopg2
from fastapi.responses import JSONResponse
from datetime import datetime
from typing import List,Dict
import secrets


app = FastAPI(title="pruve - API", docs_url="/pruve/docs", openapi_url="/pruve/openapi.json")



#uvicorn main:app --reload
# PostgreSQL database configuration
DB_HOST = "XXXXXXXXXXXXXXXXXXXXXXXXXXXX"
DB_PORT = "XXXXXXX"
DB_NAME = "XXXXXX"
DB_USER = "XXXXXX"
DB_PASSWORD = "XXXXXXXXXXXXXX"
DB_URI = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
conn = psycopg2.connect(DB_URI)
cur = conn.cursor()
# JWT Secret Key
JWT_SECRET_KEY = secrets.token_urlsafe(64)


# User Model
class User(BaseModel):
    uid: Optional[int]
    email: str
    name: str
    picture: str


class AuthResponse(BaseModel):
    uid: Optional[int]
    access_token: str
    token_type: str
    email: str
    name: str
    picture: str


class Vote(BaseModel):
    user_id: int
    option_id: int


class Option(BaseModel):
    option_id: Optional[int] = None
    option_text: str
    vote_count: Optional[int]



class Poll(BaseModel):
    poll_id: Optional[int] = None
    type: str = 'wildcard'
    user_id: int
    question: str
    options: List[Option]
    answer: str

class PollVote(BaseModel):
    poll_id: int
    type: str
    user_id: int
    question: str
    answer_id: Optional[int]
    created_at: datetime
    creator: str
    author_selected_option_id: Optional[int]
    options: List[Option]
    # vote_count: int
    user_selected: Optional[int]
    voters: List[str]
    predictionAccuracy: int
    picture: str
    total_vote_count: Optional[int]


class LeagueCreateRequest(BaseModel):
    name: str
    creator_id: int
    users: list[int]
    description: str
    matchup_id: list[int]
    is_public: bool


@app.get("/pruve/users/search/")
def search_users(user_name: str):
    # Create a cursor
    cur = conn.cursor()

    # Perform the necessary database query to search for user names
    cur.execute("SELECT uid, name, picture FROM users_pruve")
    users = cur.fetchall()

    # Perform fuzzy string matching
    matches = []
    for user in users:
        db_uid, db_user_name, db_user_picture = user
        if fuzz.ratio(user_name, db_user_name) > 50:
            matches.append({
                "uid": db_uid,
                "user_name": db_user_name,
                "picture": db_user_picture
            })

    # Prepare the response JSON
    response = {"user_name": user_name, "matches": matches[:5]}

    # Close the cursor
    cur.close()

    return response


@app.get("/pruve/leagues/{user_id}")
def get_user_leagues(user_id: int):
    # Perform the necessary database query to retrieve user's leagues and corresponding usernames
    cur.execute("SELECT l.league_name, l.league_description, u.name, u.picture "
                "FROM league_pruve l "
                "JOIN league_membership_pruve m ON l.league_id = m.league_id "
                "JOIN users_pruve u ON m.user_id = u.uid "
                "WHERE m.user_id = %s", (user_id,))
    leagues = cur.fetchall()

    # Group the results by league
    league_data = {}
    for league, description, user, image in leagues:
        if league in league_data:
            league_data[league]["users"].append({"user_name": user, "image": image})
        else:
            league_data[league] = {"league_description": description, "users": [{"user_name": user, "image": image}]}

    # Add all users in each league
    for league, data in league_data.items():
        cur.execute("SELECT u.name, u.picture "
                    "FROM league_pruve l "
                    "JOIN league_membership_pruve m ON l.league_id = m.league_id "
                    "JOIN users_pruve u ON m.user_id = u.uid "
                    "WHERE l.league_name = %s", (league,))
        users = cur.fetchall()

        # Add the users to the league data
        for user, image in users:
            data["users"].append({"user_name": user, "image": image})

    # Prepare the response JSON
    response = {"user_id": user_id, "leagues": []}

    for league, data in league_data.items():
        league_info = {"league_name": league, "league_description": data["league_description"], "users": data["users"]}
        response["leagues"].append(league_info)

    return response




@app.get("/pruve/leagues/not_member/{user_id}")
def get_non_member_leagues(user_id: int):
    # Create a cursor
    cur = conn.cursor()

    # Retrieve the leagues that the user is not a member of
    query = """
        SELECT l.league_id, l.league_name, l.league_description
        FROM league_pruve l
        WHERE l.league_id NOT IN (
            SELECT m.league_id
            FROM league_membership_pruve m
            WHERE m.user_id = %s
        )
    """
    cur.execute(query, (user_id,))
    leagues = cur.fetchall()

    # Create a dictionary to store the league data
    league_data = []

    # Iterate over the leagues and fetch additional information
    for league in leagues:
        league_id, league_name, league_description = league

        # Retrieve other users who are part of the league
        cur.execute("""
            SELECT u.uid, u.name, u.picture
            FROM users_pruve u
            JOIN league_membership_pruve m ON u.uid = m.user_id
            WHERE m.league_id = %s
        """, (league_id,))
        users = cur.fetchall()

        # Extract the user information
        user_info = []
        for user in users:
            user_id, user_name, user_picture = user
            user_info.append({"user_id": user_id, "user_name": user_name, "user_picture": user_picture})

        # Add the league data to the dictionary
        league_data.append({
            "league_id": league_id,
            "league_name": league_name,
            "league_description": league_description,
            "users": user_info
        })

    # Close the cursor
    cur.close()

    return {"user_id": user_id, "non_member_leagues": league_data}



@app.post("/pruve/leagues")
def create_league(league_request: LeagueCreateRequest):
    # Extract the data from the request
    name = league_request.name
    creator_id = league_request.creator_id
    users = league_request.users
    description = league_request.description
    matchup_id = league_request.matchup_id
    is_public = league_request.is_public

    # Check if creator_id is not already in the users list, add it
    if creator_id not in users:
        users.append(creator_id)

    # Perform the necessary operations to create the league
    # Insert the league details into the database
    cur.execute("INSERT INTO league_pruve (league_name, league_description, type, is_public, creator_id) "
                "VALUES (%s, %s, 'league', %s, %s) RETURNING league_id",
                (name, description, is_public, creator_id))
    league_id = cur.fetchone()[0]  # Retrieve the generated league_id

    # Insert the league membership details into the database
    for user_id in users:
        if user_id == creator_id:
            role = "admin"
        else:
            role = "role player"
        cur.execute("INSERT INTO league_membership_pruve (league_id, user_id, role) VALUES (%s, %s, %s)",
                    (league_id, user_id, role))

    # Insert the matchup details into the league_matchup_pruve table
    for matchup_schedule_id in matchup_id:
        cur.execute("INSERT INTO league_matchup_pruve (league_id, matchup_schedule_id) VALUES (%s, %s)",
                    (league_id, matchup_schedule_id))

    # Commit the changes to the database
    conn.commit()

    return {"message": "League created successfully"}


# Save User to DB Function
def save_user_to_db(user: User) -> int:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT uid FROM users_pruve WHERE email = %s", (user.email,))
            result = cur.fetchone()
            if result is not None:
                uid = result[0]
                return uid

            cur.execute("INSERT INTO users_pruve (email, name, picture) VALUES (%s, %s, %s) RETURNING uid",
                        (user.email, user.name, user.picture))
            uid = cur.fetchone()[0]
            conn.commit()

            return uid
    except Exception as e:
        print("Error saving user to DB:", str(e))
        raise



# Create Access Token Function
def create_access_token(user_email: str) -> str:
    access_token = jwt.encode(
        {"sub": user_email},
        JWT_SECRET_KEY,
        algorithm="HS256"
    )
    return access_token

class ConversationModel(BaseModel):
    id: int
    type: str
    user: dict
    time: datetime
    teams: List
    predictionText: str
    commentCount: int
    reactions: List
    link : str

class Matchschedule(BaseModel):
    team1: str
    team2: str
    time: Optional[datetime]
    votecount1: int
    votecount2: int
    venue: str
    image1 : str
    image2: str
    type: str

class wildcardModel(BaseModel):
    id: int
    type: str
    user: dict
    time: datetime
    totalvotes: int
    voterlist: List
    question: str
    options: List

# Retrieve Conversations from DB Function
def get_conversations_from_db() -> List[ConversationModel]:
    conversations = []
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM conversation_tablev1")
        rows = cur.fetchall()
        for row in rows:
            conversation = ConversationModel(
                id=row[0],
                type=row[1],
                user=row[2],
                time=row[3],
                teams=row[4],
                predictionText=row[5],
                commentCount=row[6],
                reactions=row[7],
                link = row[8]
            )
            conversations.append(conversation)
    return conversations

# Retrieve wildcrad from DB Function
def get_wildcards_from_db() -> List[wildcardModel]:
    wildcards = []
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM wildcard_tablev1")
        rows = cur.fetchall()
        for row in rows:
            wildcard = wildcardModel(
                id=row[0],
                type=row[1],
                user=row[2],
                time=row[3],
                totalvotes=row[4],
                voterlist=row[5],
                question=row[6],
                options=row[7]
            )
            wildcards.append(wildcard)
    return wildcards

def get_matchcard_from_db() -> List[Matchschedule]:
    matchschedules = []
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM matchschedulev2")
        rows = cur.fetchall()
        for row in rows:
            matchschedule = Matchschedule(
                team1=row[1],
                team2=row[2],
                time=row[3],
                votecount1=row[4],
                votecount2=row[5],
                venue=row[6],
                image1 = row[7],
                image2= row[8],
                type=row[9]
            )
            matchschedules.append(matchschedule)
    return matchschedules

# Get Conversations API Endpoint
@app.get("/pruve/conversations", response_model=List[ConversationModel])
async def get_conversations():
    try:
        conversations = get_conversations_from_db()
        return conversations
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

# Get Conversations API Endpoint
@app.get("/pruve/wildcards", response_model=List[wildcardModel])
async def get_wildcards():
    try:
        wildcards = get_wildcards_from_db()
        return wildcards
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
    
@app.get("/pruve/matchschedule", response_model=List[Matchschedule])
async def get_matchschedules():
    try:
        matchschedules = get_matchcard_from_db()
        return matchschedules
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.get("/pruve/data", response_model=List[Union[ConversationModel, Matchschedule, wildcardModel]])
async def get_data():
    try:
        conversations = get_conversations_from_db()
        matchschedules = get_matchcard_from_db()
        wildcards = get_wildcards_from_db()
        data = conversations + matchschedules + wildcards
        return data
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
    

# Create User API Endpoint
@app.post("/pruve/user", response_model=AuthResponse)
async def create_user(user: User):
    try:
        # Save User to DB and generate uid
        uid = save_user_to_db(user)
    except HTTPException as e:
        if e.status_code == 400:
            # User already exists, return uid
            return {"uid": user.uid}
        else:
            print("Error saving user to DB:", str(e))
            raise

    # Create Access Token
    access_token = create_access_token(user.email)

    # Create and Return Auth Response
    auth_response = AuthResponse(
        uid=uid,
        access_token=access_token,
        token_type="bearer",
        email=user.email,
        name=user.name,
        picture=user.picture
    )
    return auth_response.dict()


@app.post('/pruve/create_polls', response_model=Poll)
def create_poll(poll: Poll):
    try:
        # Check if the user exists
        cur.execute("SELECT COUNT(*) FROM users_pruve WHERE uid = %s", (poll.user_id,))
        if cur.fetchone()[0] == 0:
            raise HTTPException(status_code=404, detail='User not found')

        # Convert question and answer to lowercase
        question_lower = poll.question.lower()
        answer_lower = poll.answer.lower()

        # Insert the poll into the 'poll_pruve' table
        cur.execute("INSERT INTO poll_pruve (type, user_id, question, created_at) "
                    "VALUES (%s, %s, %s, %s) RETURNING poll_id, created_at",
                    ('wildcard', poll.user_id, question_lower, datetime.now()))
        result = cur.fetchone()
        poll_id = result[0]
        created_at = result[1]

        # Insert the options into the 'option_pruve' table
        options = []
        for option in poll.options:
            option_text_lower = option.option_text.lower()  # Convert option text to lowercase
            cur.execute("INSERT INTO option_pruve_v1 (poll_id, option_text) VALUES (%s, %s) RETURNING option_id",
                        (poll_id, option_text_lower))
            option_id = cur.fetchone()[0]
            options.append({"option_id": option_id, "option_text": option_text_lower})

        # Find the selected option_id based on the answer text
        selected_option = next((option for option in options if option["option_text"] == answer_lower), None)
        if not selected_option:
            raise HTTPException(status_code=400, detail='Invalid answer')

        selected_option_id = selected_option["option_id"]

        # Insert the answer into the 'answer_pruve' table
        cur.execute("INSERT INTO answer_pruve (poll_id, creator_id, option_id, answer_text) "
                    "VALUES (%s, %s, %s, %s) RETURNING answer_id",
                    (poll_id, poll.user_id, selected_option_id, answer_lower))
        answer_id = cur.fetchone()[0]

        # Insert a vote for the answer in the 'vote_pruve' table
        cur.execute("INSERT INTO vote_pruve (poll_id, option_id, user_id) VALUES (%s, %s, %s)",
                    (poll_id, selected_option_id, poll.user_id))

        # Commit the transaction
        conn.commit()

        new_poll = Poll(poll_id=poll_id, user_id=poll.user_id, question=poll.question,
                        options=options, answer=poll.answer, created_at=created_at)
        return new_poll
    except psycopg2.Error as e:
        conn.rollback()
        error_message = str(e)
        print("Error message:", error_message)
        raise HTTPException(status_code=500, detail='Failed to create poll')







@app.post('/pruve/polls/{poll_id}/vote', response_model=Vote)
def vote(poll_id: int, vote: Vote):
    try:
        # Check if the poll exists
        cur.execute("""
            SELECT COUNT(*) FROM poll_pruve WHERE poll_id = %s
        """, (poll_id,))
        if cur.fetchone()[0] == 0:
            raise HTTPException(status_code=404, detail='Poll not found')

        # Check if the option exists for the poll
        cur.execute("""
            SELECT COUNT(*) FROM option_pruve_v1 WHERE option_id = %s AND poll_id = %s
        """, (vote.option_id, poll_id))
        if cur.fetchone()[0] == 0:
            # print("Option ID:", vote.option_id)
            # print("Poll ID:", poll_id)
            raise HTTPException(status_code=400, detail='Invalid option for the poll')

        # Check if the user has already voted for the poll
        cur.execute("""
            SELECT COUNT(*) FROM vote_pruve WHERE user_id = %s AND poll_id = %s
        """, (vote.user_id, poll_id))
        if cur.fetchone()[0] > 0:
            raise HTTPException(status_code=400, detail='User has already voted for the poll')

        # Insert the vote into the 'vote' table
        cur.execute("""
            INSERT INTO vote_pruve (user_id, poll_id, option_id)
            VALUES (%s, %s, %s)
            RETURNING vote_id
        """, (vote.user_id, poll_id, vote.option_id))
        vote_id = cur.fetchone()[0]

        # Commit the transaction
        conn.commit()

        # Create a new Vote object without vote_id and poll_id
        new_vote = Vote(user_id=vote.user_id, option_id=vote.option_id)

        return new_vote
    except HTTPException as e:
        print("Error details:", e.detail)
        conn.rollback()
        raise HTTPException(status_code=500, detail='Failed to record vote')

def get_vote_count(option_id):
    cur.execute("""
        SELECT COUNT(*) AS vote_count
        FROM vote_pruve
        WHERE option_id = %s
    """, (option_id,))
    vote_count = cur.fetchone()[0]
    return vote_count


@app.get('/user/{user_id}/polls', response_model=List[PollVote])
def get_user_polls(user_id: int):
    try:
        # Fetch all polls and related information, including the picture column
        cur.execute("""
            SELECT p.poll_id, p.type, p.user_id, p.question, o.option_id AS answer_id, p.created_at, u.name AS creator,
                o.option_id, o.option_text, u.picture,
                COUNT(v.option_id) AS vote_count,
                MAX(CASE WHEN v.user_id = %s THEN v.option_id END) AS user_selected,
                ARRAY_AGG(uv.name) FILTER (WHERE uv.name IS NOT NULL) AS voters
            FROM poll_pruve AS p
            INNER JOIN users_pruve AS u ON p.user_id = u.uid
            INNER JOIN option_pruve_v1 AS o ON p.poll_id = o.poll_id
            LEFT JOIN vote_pruve AS v ON o.option_id = v.option_id
            LEFT JOIN users_pruve AS uv ON v.user_id = uv.uid
            WHERE p.user_id = %s
            GROUP BY p.poll_id, p.type, p.user_id, p.question, o.option_id, o.option_text, answer_id, p.created_at, u.name, u.picture
        """, (user_id, user_id))

        results = cur.fetchall()
        poll_votes = []
        for row in results:
            poll_id, poll_type, poll_user_id, question, answer_id, created_at, creator, option_id, option_text, picture, vote_count, user_selected, voters = row

            # Check if the poll already exists in poll_votes list
            existing_poll = next((poll for poll in poll_votes if poll.poll_id == poll_id), None)
            if existing_poll:
                existing_poll.options.append({"option_id": option_id, "option_text": option_text, "vote_count": vote_count})
                if user_selected:
                    existing_poll.user_selected = user_selected
                if voters:
                    existing_poll.voters = voters
            else:
                poll_vote = PollVote(
                    poll_id=poll_id,
                    type=poll_type,
                    user_id=poll_user_id,
                    question=question,
                    answer_id=answer_id,  # Use the answer_id instead of answer text
                    created_at=created_at,
                    authorSelectedId=creator,
                    predictionAccuracy=76,
                    picture=picture,
                    options=[Option(option_id=option_id, option_text=option_text, vote_count=vote_count)],
                    # vote_count=vote_count,
                    user_selected=user_selected,
                    voters=voters if voters else []
                    # predictionAccuracy=76,
                    # picture=picture  # Set the picture field
                )
                poll_votes.append(poll_vote)

        # Fetch the total vote count for every poll
        for poll_vote in poll_votes:
            poll_vote.total_vote_count = sum(option.vote_count for option in poll_vote.options)

        return poll_votes

    except psycopg2.Error as e:
        conn.rollback()
        error_message = str(e)
        print("Error message:", error_message)
        raise HTTPException(status_code=500, detail='Failed to fetch polls')


@app.get('/user/{user_id}/polls', response_model=List[PollVote])
def get_user_polls(user_id: int):
    try:
        # Fetch all polls and related information, including the picture column
        cur.execute("""
            SELECT p.poll_id, p.type, p.user_id, p.question, o.option_id AS answer_id, p.created_at, u.name AS creator,
                o.option_id, o.option_text,
                COUNT(v.option_id) AS vote_count,
                MAX(CASE WHEN v.user_id = %s THEN v.option_id END) AS user_selected,
                u.picture  -- Fetch the picture column
            FROM poll_pruve AS p
            INNER JOIN users_pruve AS u ON p.user_id = u.uid
            INNER JOIN option_pruve_v1 AS o ON p.poll_id = o.poll_id
            LEFT JOIN vote_pruve AS v ON o.option_id = v.option_id
            GROUP BY p.poll_id, p.type, p.user_id, p.question, o.option_id, o.option_text, answer_id, p.created_at, u.name, u.picture
        """, (user_id,))

        results = cur.fetchall()
        poll_votes = []
        for row in results:
            poll_id, poll_type, poll_user_id, question, answer_id, created_at, creator, option_id, option_text, vote_count, user_selected, picture = row

            # Check if the poll already exists in poll_votes list
            existing_poll = next((poll for poll in poll_votes if poll.poll_id == poll_id), None)
            if existing_poll:
                existing_poll.options.append({"option_id": option_id, "option_text": option_text, "vote_count": vote_count})
                if user_selected:
                    existing_poll.user_selected = user_selected
            else:
                poll_vote = PollVote(
                    poll_id=poll_id,
                    type=poll_type,
                    user_id=poll_user_id,
                    question=question,
                    answer_id=answer_id,  # Use the answer_id instead of answer text
                    created_at=created_at,
                    authorSelectedId=creator,
                    options=[Option(option_id=option_id, option_text=option_text, vote_count=vote_count)],
                    user_selected=user_selected,
                    voters=voters if voters else [],
                    predictionAccuracy=76,
                    picture=picture
                )
                # Calculate the total vote count for the poll
                total_vote_count = sum(option.vote_count for option in poll_vote.options)
                poll_vote.total_vote_count = total_vote_count

                poll_votes.append(poll_vote)
                poll_votes[-1].total_vote_count = total_vote_count
        return poll_votes

    except psycopg2.Error as e:
        conn.rollback()
        error_message = str(e)
        print("Error message:", error_message)
        raise HTTPException(status_code=500, detail='Failed to fetch polls')






@app.get('/pruve/user/{user_id}/polls', response_model=List[PollVote])
def get_user_polls(user_id: int):
    try:
        # Fetch all polls and related information, including the picture column and all options
        cur.execute("""
            SELECT p.poll_id, p.type, p.user_id, p.question, a.option_id AS answer_id, p.created_at, u.name AS creator,
                ans.option_id AS author_selected_option_id,
                o.option_id, o.option_text,
                COUNT(v.option_id) AS vote_count,
                (SELECT v1.option_id FROM vote_pruve v1 WHERE v1.user_id = %s AND v1.poll_id = p.poll_id LIMIT 1) AS user_selected,
                ARRAY_AGG(uv.name) FILTER (WHERE uv.name IS NOT NULL) AS voters,
                u.picture,
                SUM(COUNT(v.option_id)) OVER (PARTITION BY p.poll_id) AS total_vote_count
            FROM poll_pruve AS p
            INNER JOIN users_pruve AS u ON p.user_id = u.uid
            INNER JOIN option_pruve_v1 AS o ON p.poll_id = o.poll_id
            LEFT JOIN answer_pruve AS a ON p.poll_id = a.poll_id
            LEFT JOIN option_pruve_v1 AS ans ON a.option_id = ans.option_id
            LEFT JOIN vote_pruve AS v ON o.option_id = v.option_id
            LEFT JOIN users_pruve AS uv ON v.user_id = uv.uid

            GROUP BY p.poll_id, p.type, p.user_id, p.question, a.option_id, ans.option_id, o.option_id, o.option_text, answer_id, p.created_at, u.name, u.picture
            ORDER BY p.poll_id DESC
        """, (user_id,))

        results = cur.fetchall()
        poll_votes = {}
        for row in results:
            poll_id, poll_type, poll_user_id, question, answer_id, created_at, creator, author_selected_option_id, option_id, option_text, vote_count, user_selected, voters, picture, total_vote_count = row
            print(user_selected)
            if poll_id not in poll_votes:
                poll_votes[poll_id] = PollVote(
                    poll_id=poll_id,
                    type=poll_type,
                    user_id=poll_user_id,
                    question=question,
                    answer_id=answer_id,
                    created_at=created_at,
                    creator=creator,
                    predictionAccuracy=76,
                    picture=picture,
                    options=[],
                    user_selected=user_selected,
                    voters=[],
                    author_selected_option_id=author_selected_option_id,
                    total_vote_count=total_vote_count
                )

            poll_votes[poll_id].options.append(
                Option(option_id=option_id, option_text=option_text, vote_count=vote_count))
            if voters:
                poll_votes[poll_id].voters.extend(voters)

        return list(poll_votes.values())

    except psycopg2.Error as e:
        conn.rollback()
        error_message = str(e)
        print("Error message:", error_message)
        raise HTTPException(status_code=500, detail='Failed to fetch polls')

@app.get('/pruve/polls/{poll_id}', response_model=Dict[str, Union[Dict[str, Union[int, str, List[str], User]], Dict[str, Union[int, List[Dict[str, Union[int, str]]]]]]])
def get_poll_and_results(poll_id: int):
    try:
        # Check if the poll exists
        cur.execute("""
            SELECT * FROM poll WHERE poll_id = %s
        """, (poll_id,))
        poll_data = cur.fetchone()
        if poll_data is None:
            raise HTTPException(status_code=404, detail='Poll not found')

        # Retrieve the options for the poll
        cur.execute("""
            SELECT option_text FROM option WHERE poll_id = %s
        """, (poll_id,))
        options = [row[0] for row in cur.fetchall()]

        # Retrieve the details of the user who created the poll
        cur.execute("""
            SELECT user_id, name, email, picture FROM users WHERE user_id = %s
        """, (poll_data[2],))
        user_data = cur.fetchone()
        if user_data is None:
            raise HTTPException(status_code=404, detail='User not found')

        user = User(user_id=user_data[0], name=user_data[1], email=user_data[2], picture=user_data[3])

        poll = {
            'poll_id': poll_data[0],
            'type': poll_data[1],
            'user_id': poll_data[2],
            'question': poll_data[3],
            'options': options,
            'user': user
        }

        # Retrieve the total count of votes
        cur.execute("""
            SELECT COUNT(*) FROM vote WHERE poll_id = %s
        """, (poll_id,))
        total_count = cur.fetchone()[0]

        # Retrieve the list of users who voted
        cur.execute("""
            SELECT DISTINCT user_id FROM vote WHERE poll_id = %s
        """, (poll_id,))
        voted_users = [row[0] for row in cur.fetchall()]

        # Retrieve the details of the users who voted
        voted_users_details = []
        for voted_user_id in voted_users:
            cur.execute("""
                SELECT user_id, name, email, picture FROM users WHERE user_id = %s
            """, (voted_user_id,))
            voted_user_data = cur.fetchone()
            if voted_user_data is not None:
                voted_user = {
                    'user_id': voted_user_data[0],
                    'name': voted_user_data[1],
                    'email': voted_user_data[2],
                    'picture': voted_user_data[3]
                }
                voted_users_details.append(voted_user)

        results = {
            'total_count': total_count,
            'voted_users': voted_users_details
        }

        response = {
            'poll': poll,
            'results': results
        }

        return response
    except psycopg2.Error as e:
        raise HTTPException(status_code=500, detail='Failed to retrieve poll and results')



def get_options_for_poll(poll_id: int) -> List[Option]:
    cur.execute("SELECT option_id, option_text FROM option WHERE poll_id = %s", (poll_id,))
    option_rows = cur.fetchall()

    options = []
    for option_row in option_rows:
        option_id, option_text = option_row
        option = Option(option_id=option_id, option_text=option_text)
        options.append(option)

    return options




@app.get('/pruve/polls', response_model=List[Poll])
def get_all_polls():
    try:
        cur.execute("SELECT poll_id, user_id, question FROM poll")
        poll_rows = cur.fetchall()

        polls = []
        for poll_row in poll_rows:
            poll_id, user_id, question = poll_row
            options = get_options_for_poll(poll_id)  # Fetch options from the database
            poll = Poll(poll_id=poll_id, user_id=user_id, question=question, options=options)
            polls.append(poll)

        return polls
    except psycopg2.Error as e:
        raise HTTPException(status_code=500, detail='Failed to fetch polls')

class Comment(BaseModel):
    comment_id: int
    type: str
    user_details: dict
    time: str
    teams: List
    comment_text: str

@app.get("/pruve/comments/{match_number}")
def get_comments(match_number: int) -> List[Comment]:
    try:
        # Execute the SQL query
        query = """
        SELECT
            c.comment_id,
            c.type,
            json_build_object('uid', u.uid, 'email', u.email, 'name', u.name, 'picture', u.picture) AS user_details,
            c.time,
            json_build_array(
                json_build_object('nickName', t1."nickName", 'isUserSelected', mv.team_id = t1.team_id),
                json_build_object('nickName', t2."nickName", 'isUserSelected', mv.team_id = t2.team_id)
            ) AS teams,
            c.comment_text
        FROM
            public.comments_table_pruve AS c
            INNER JOIN public.users_pruve AS u ON c.user_id = u.uid
            INNER JOIN public.matchschedule AS m ON c.match_number = m.match_number
            INNER JOIN public.team_list AS t1 ON m.team1_id = t1.team_id
            INNER JOIN public.team_list AS t2 ON m.team2_id = t2.team_id
            LEFT JOIN public.match_vote_pruve AS mv ON c.vote_id = mv.vote_id
        WHERE
            c.match_number = %s;
        """

        cur.execute(query, (match_number,))
        rows = cur.fetchall()

        # Construct the Comment objects from the query results
        comments = []
        for row in rows:
            user_details = {
                "uid": row[2]['uid'],
                "email": row[2]['email'],
                "name": row[2]['name'],
                "picture": row[2]['picture']
            }
            comment = Comment(
                comment_id=row[0],
                type=row[1],
                user_details=user_details,
                time=row[3].strftime("%Y-%m-%d %H:%M:%S"),
                teams=row[4],
                comment_text=row[5]
            )
            comments.append(comment)

        return comments

    except (Exception, psycopg2.Error) as error:
        raise HTTPException(status_code=500, detail=str(error))

@app.get("/pruve/comments/")
def get_comments():
    try:
        # Execute the SQL query
        query = """
        SELECT
            c.comment_id,
            c.type,
            json_build_object('uid', u.uid, 'email', u.email, 'name', u.name, 'picture', u.picture) AS user_details,
            c.time,
            json_build_array(
                json_build_object('nickName', t1."nickName", 'isUserSelected', mv.team_id = t1.team_id),
                json_build_object('nickName', t2."nickName", 'isUserSelected', mv.team_id = t2.team_id)
            ) AS teams,
            c.comment_text
        FROM
            public.comments_table_pruve AS c
            INNER JOIN public.users_pruve AS u ON c.user_id = u.uid
            INNER JOIN public.matchschedule AS m ON c.match_number = m.match_number
            INNER JOIN public.team_list AS t1 ON m.team1_id = t1.team_id
            INNER JOIN public.team_list AS t2 ON m.team2_id = t2.team_id
            LEFT JOIN public.match_vote_pruve AS mv ON c.vote_id = mv.vote_id
        """

        cur.execute(query)
        rows = cur.fetchall()

        # Construct the Comment objects from the query results
        comments = []
        for row in rows:
            user_details = {
                "uid": row[2]['uid'],
                "email": row[2]['email'],
                "name": row[2]['name'],
                "picture": row[2]['picture']
            }
            comment = Comment(
                comment_id=row[0],
                type=row[1],
                user_details=user_details,
                time=row[3].strftime("%Y-%m-%d %H:%M:%S"),
                teams=row[4],
                comment_text=row[5]
            )
            comments.append(comment)

        return comments

    except (Exception, psycopg2.Error) as error:
        raise HTTPException(status_code=500, detail=str(error))

class MatchVoteCreate(BaseModel):
    team_id: int
    user_id: int

class CommentCreate(BaseModel):
    user_id: int
    comment_text: str

#Triggering both matchup vote and conversation
@app.post("/pruve/{match_number}/match_vote_and_comment")
async def create_match_vote_and_comment(match_number: int, match_vote: MatchVoteCreate, comment: CommentCreate):
    try:
        # Insert the data into the match_vote_pruve table
        match_vote_insert_query = """
            INSERT INTO match_vote_pruve (team_id, match_number, user_id)
            VALUES (%s, %s, %s)
            RETURNING vote_id
        """
        cur.execute(match_vote_insert_query, (match_vote.team_id, match_number, match_vote.user_id))
        vote_id = cur.fetchone()[0]

        # Insert the data into the comments_table_pruve table
        comment_insert_query = """
            INSERT INTO comments_table_pruve (user_id, match_number, vote_id, comment_text)
            VALUES (%s, %s, %s, %s)
        """
        cur.execute(comment_insert_query, (comment.user_id, match_number, vote_id, comment.comment_text))

        conn.commit()

        return {"message": "Data inserted successfully"}

    except (Exception, psycopg2.Error) as error:
        raise HTTPException(status_code=500, detail=str(error))

class MatchcardModel(BaseModel):
    match_number: int
    team1_id: int
    team1_name: str
    team1_icon: str
    team2_id : int
    team2_name: str
    team2_icon: str
    match_time:  Optional[datetime]
    venue : str
    type: str
    description: str
    book_tickets:str
    
#Get request of matchcards
@app.get("/pruve/{user_id}/matchcards/", response_model=List[MatchcardModel])
def get_matches(user_id: int):
    try:
        query = """
        SELECT
            ms.match_number,
            ms.team1_id,
            tl1.name AS team1_name,
            tl1.icon AS team1_icon,
            ms.team2_id,
            tl2.name AS team2_name,
            tl2.icon AS team2_icon,
            ms.type,
            ms.match_time,
            ms.venue,
            ms.description,
            ms.book_tickets
        FROM
            public.matchschedule AS ms
        JOIN
            public.team_list AS tl1 ON ms.team1_id = tl1.team_id
        JOIN
            public.team_list AS tl2 ON ms.team2_id = tl2.team_id
        WHERE
            ms.match_number NOT IN (
                SELECT match_number FROM public.match_vote_pruve WHERE user_id = %s
            );
        """

        cur.execute(query, (user_id,))
        results = cur.fetchall()

        matches = []
        for result in results:
            match = MatchcardModel(
                match_number=result[0],
                team1_id = result[1],
                team1_name=result[2],
                team1_icon=result[3],
                team2_id = result[4],
                team2_name=result[5],
                team2_icon=result[6],
                type=result[7],
                match_time=result[8],
                venue=result[9],
                description=result[10],
                book_tickets = result[11]
            )
            matches.append(match)

        return matches
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
