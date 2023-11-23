from flask import Flask, jsonify, request
import logging
import pytesseract
import datetime
import re
import requests
import os
from tempfile import NamedTemporaryFile
from urllib.parse import urlparse
from PIL import Image
from openai import OpenAI

client = OpenAI(
    api_key= "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"
)

# Setting up logging
logging.basicConfig(level=logging.INFO)

# Initialize Flask app
app = Flask(__name__)

class LoanApprovalSystem:
    def download_file(self, url):
        '''Download a file from a URL to a temporary file.'''
        response = requests.get(url)
        response.raise_for_status()
        temp_file = NamedTemporaryFile(delete=False, suffix='.png')
        temp_file.write(response.content)
        temp_file.close()
        return temp_file.name

    def is_url(self, path):
        '''Check if the given path is a URL.'''
        try:
            result = urlparse(path)
            return all([result.scheme, result.netloc])
        except ValueError:
            return False
        
    def get_file_path(self, path):
        '''Get file path from URL or local path.'''
        if self.is_url(path):
            return self.download_file(path)
        else:
            return path
        
    def image_to_text(self, image_path):
        '''Convert an image file to text using pytesseract OCR.'''
        try:
            text = pytesseract.image_to_string(Image.open(image_path))
            return text
        except Exception as e:
            logging.error(f"Error processing image: {e}")
            raise

    def extract_from_files(self, payslip_path, credit_report_path, json_data):
        '''Extract net salary and credit score from given image file paths or URLs.'''
        payslip_real_path = self.get_file_path(payslip_path)
        credit_report_real_path = self.get_file_path(credit_report_path)
        payslip_text = self.image_to_text(payslip_real_path)
        credit_report_text = self.image_to_text(credit_report_real_path)

        gross_income_match = re.search(r'Monthly Gross Income: (\\d+)', payslip_text)
        if gross_income_match:
            gross_income = int(gross_income_match.group(1))
        else:
            gross_income = json_data.get('Monthly Gross Income', 0)

        credit_score_match = re.search(r'Credit Score: (\\d+)', credit_report_text)
        if credit_score_match:
            credit_score = int(credit_score_match.group(1))
        else:
            credit_score = 0

        return gross_income, credit_score

    def evaluate_application(self, application, json_data):
        '''Evaluate a loan application and return the decision along with the criteria evaluation.'''
        gross_income, credit_score = self.extract_from_files(application['Payslip'], application['Credit Report'], json_data)
        dti = application['Total Monthly Debt Obligations'] / gross_income
        criteria_evaluation = {}
        rules_passed = 0

        criteria_evaluation['Debt-to-Income Ratio <= 0.43'] = dti <= 0.43
        criteria_evaluation['Credit Score >= 670'] = credit_score >= 670
        criteria_evaluation['Sector of Employment in Preferred List'] = application['Sector of Employment'] in ['Government Jobs', 'Healthcare', 'IT', 'Finance']
        criteria_evaluation['Number of Existing Loans < 5'] = application['Number of Existing Loans'] < 5
        criteria_evaluation['Loan Amount <= 60% of Annual Income'] = application['Desired Loan Amount'] <= 0.6 * (12 * gross_income)
        criteria_evaluation['Duration at Current Job >= 2 Years'] = application['Duration at Current Job'] >= 2
        criteria_evaluation['No History of Bankruptcy'] = application['History of Bankruptcy'] == 'No'

        age = datetime.datetime.now().year - int(application['Date of Birth'].split('-')[0])
        criteria_evaluation['Age Between 18 and 70'] = 18 <= age <= 70
        criteria_evaluation['Residency Status as Permanent Resident or Citizen'] = application['Residency Status'] in ['Permanent Resident', 'Citizen']

        for key, value in criteria_evaluation.items():
            if value:
                rules_passed += 1

        decision = 'Approved' if rules_passed >= 8 else 'Declined'
        return decision, criteria_evaluation
    
    def generate_explanation(self, application, decision, criteria_evaluation):
        """Generate a concise, three-sentence explanation for the loan decision using gpt-3.5-turbo-instruct."""
        criteria_details = "\n".join([f"- {criterion}: {'Met' if met else 'Not Met'}" for criterion, met in criteria_evaluation.items()])
        prompt = f"""
        Based on the following criteria evaluation, provide a concise, three-sentence explanation for why this specific loan application was {decision.lower()}.
        Decision: {decision}. 
        Application details: {application}
        Criteria evaluation:
        {criteria_details}
        """

        try:
            response = client.completions.create(
                model="gpt-3.5-turbo-instruct",
                prompt=prompt,
                max_tokens=150  # Adjust as needed
            )
            explanation = response.choices[0].text.strip()
            # Split the response into sentences and take the first three
            explanation_sentences = explanation.split('. ')
            concise_explanation = '. '.join(explanation_sentences[:3]) + '.'
            return concise_explanation
        except Exception as e:
            logging.error(f"Error generating explanation: {e}")
            return "Explanation not available"

    def process_application(self, application):
        '''Process a single loan application.'''
        decision, criteria_evaluation = self.evaluate_application(application, application)
        explanation = self.generate_explanation(application, decision, criteria_evaluation)
        return {'application_id': application['_id'], 'result': decision, 'explanation': explanation}


@app.route('/process-entry', methods=['POST'])
def process_entry():
    '''API endpoint to receive and process POST data.'''
    try:
        # Receiving JSON data from the POST request
        entry_data = request.json['response']
        logging.info(f"Received data: {entry_data}")

        # Processing the data using LoanApprovalSystem
        loan_system = LoanApprovalSystem()
        processed_data = loan_system.process_application(entry_data)
        
        # Returning the processed data as JSON
        return jsonify(result=processed_data), 200
    except Exception as e:
        logging.error(f"Error in processing entry: {e}")
        return jsonify(error=str(e)), 500

# Run the Flask app if this file is executed directly
if __name__ == '__main__':
    app.run(debug=True)
